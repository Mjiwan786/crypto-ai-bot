#!/usr/bin/env python3
"""
Bar Reaction Strategy Backtest Runner

Simplified backtest harness for bar_reaction_5m strategy with YAML config loading.

Usage:
    # Use default aggressive config
    python scripts/run_bar_reaction_backtest.py

    # Use custom config
    python scripts/run_bar_reaction_backtest.py --config config/bar_reaction_5m_aggressive.yaml

    # Custom lookback and capital
    python scripts/run_bar_reaction_backtest.py --lookback 365 --capital 20000

    # Save results
    python scripts/run_bar_reaction_backtest.py \\
        --config config/bar_reaction_5m_aggressive.yaml \\
        --lookback 180 \\
        --output out/aggressive_180d.json
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np
import pandas as pd
import yaml

from strategies.bar_reaction_5m import BarReaction5mStrategy
from strategies.api import SignalSpec

logger = logging.getLogger(__name__)


def load_yaml_config(config_path: Path) -> dict:
    """Load strategy configuration from YAML file"""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    return config


def generate_synthetic_ohlcv(
    pair: str,
    timeframe_minutes: int,
    lookback_days: int,
    seed: int = 42
) -> pd.DataFrame:
    """
    Generate synthetic OHLCV data for backtesting.

    NOTE: Always generates 1-minute bars regardless of timeframe_minutes parameter.
    This is required because the bar_reaction_5m strategy expects 1m data and rolls it up internally.

    Args:
        pair: Trading pair (e.g., "BTC/USD")
        timeframe_minutes: Ignored - always generates 1m bars
        lookback_days: Days of history
        seed: Random seed for reproducibility

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume (1-minute bars)
    """
    np.random.seed(seed)

    # Always generate 1-minute bars (strategy will roll up to 5m)
    bars_per_day = 1440  # 1440 minutes per day
    total_bars = lookback_days * bars_per_day

    # Base price
    if "BTC" in pair:
        base_price = 50000.0
        volatility = 0.02
    elif "ETH" in pair:
        base_price = 3000.0
        volatility = 0.025
    elif "SOL" in pair:
        base_price = 100.0
        volatility = 0.03
    elif "ADA" in pair:
        base_price = 0.50
        volatility = 0.035
    elif "AVAX" in pair:
        base_price = 35.0
        volatility = 0.04
    else:
        base_price = 100.0
        volatility = 0.02

    # Generate timestamps (always 1-minute frequency)
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=lookback_days)
    timestamps = pd.date_range(
        start=start_date,
        end=end_date,
        freq="1min"  # Always 1-minute bars
    )[:total_bars]

    # Price series with trend and random walk
    trend = np.linspace(0, base_price * 0.1, total_bars)
    returns = np.random.normal(0, volatility, total_bars)
    price_multiplier = np.exp(np.cumsum(returns))
    close_prices = base_price * price_multiplier + trend

    # Generate OHLC
    open_prices = close_prices * (1 + np.random.normal(0, volatility / 4, total_bars))
    high_prices = np.maximum(open_prices, close_prices) * (1 + np.abs(np.random.normal(0, volatility / 2, total_bars)))
    low_prices = np.minimum(open_prices, close_prices) * (1 - np.abs(np.random.normal(0, volatility / 2, total_bars)))
    volumes = np.random.lognormal(10, 1, total_bars)

    # Create DataFrame
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volumes,
    })

    return df


def run_simple_backtest(
    strategy: BarReaction5mStrategy,
    df_5m: pd.DataFrame,
    initial_capital: float,
    fee_bps: float = 16.0,
    slippage_bps: float = 2.0,
) -> dict:
    """
    Run simple backtest on 5m OHLCV data.

    Args:
        strategy: Bar reaction strategy instance
        df_5m: 5-minute OHLCV DataFrame
        initial_capital: Starting capital in USD
        fee_bps: Trading fee in basis points
        slippage_bps: Slippage in basis points

    Returns:
        Dictionary with backtest metrics
    """
    capital = initial_capital
    trades = []
    equity_curve = [capital]
    max_equity = capital
    max_dd_pct = 0.0

    # Prepare strategy (rolls up 1m → 5m and calculates features)
    symbol = "BTC/USD"
    strategy.prepare(symbol, df_5m)

    # Get the processed 5m features from strategy cache
    df_5m_features = strategy._cached_features

    if df_5m_features is None or len(df_5m_features) == 0:
        logger.error("Strategy prepare() did not generate any 5m features!")
        return {
            'total_return_pct': 0.0,
            'profit_factor': 0.0,
            'sharpe_ratio': 0.0,
            'max_dd_pct': 0.0,
            'win_rate_pct': 0.0,
            'total_trades': 0,
            'winners': 0,
            'losers': 0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'final_capital': initial_capital,
            'period_days': 0,
            'status': 'ERROR_NO_FEATURES',
        }

    logger.info(f"Strategy prepared {len(df_5m_features)} 5m bars from {len(df_5m)} 1m bars")
    logger.info(f"Running backtest on {len(df_5m_features)} 5m bars...")

    # Debug counters
    should_trade_rejects = 0
    no_signal_count = 0
    trade_count = 0

    # Iterate through 5m bars (not 1m bars!)
    for i in range(len(df_5m_features)):
        if i < strategy.atr_window + 1:
            continue  # Need warmup period

        # Get current bar subset (5m features)
        df_current = df_5m_features.iloc[:i+1]

        # Check if should trade (with debug logging)
        if not strategy.should_trade(symbol, df_current):
            should_trade_rejects += 1
            equity_curve.append(capital)

            # Debug: Log first 5 rejections
            if should_trade_rejects <= 5:
                latest = df_current.iloc[-1]
                atr_pct = latest.get("atr_pct", 0.0)
                logger.warning(
                    f"should_trade() rejected bar {i}: "
                    f"ATR%={atr_pct:.4f}%, "
                    f"range=[{strategy.min_atr_pct:.4f}% - {strategy.max_atr_pct:.4f}%]"
                )
            continue

        # Generate signals
        spread_bps = 5.0  # Assume constant spread
        current_price = float(df_current.iloc[-1]['close'])  # Get current bar close price
        signals = strategy.generate_signals(
            symbol=symbol,
            current_price=current_price,
            df_5m=df_current,
        )

        if not signals:
            no_signal_count += 1
            equity_curve.append(capital)

            # Debug: Log first 5 no-signal cases
            if no_signal_count <= 5:
                latest = df_current.iloc[-1]
                move_bps = latest.get("move_bps", 0.0)
                logger.warning(
                    f"generate_signals() returned empty at bar {i}: "
                    f"move_bps={move_bps:.2f}, "
                    f"trigger_threshold={strategy.trigger_bps_up:.2f}"
                )
            continue

        trade_count += 1

        # Size positions
        positions = strategy.size_positions(
            signals=signals,
            account_equity_usd=Decimal(str(capital)),
        )

        # Execute trades (simplified: immediate fill at entry)
        for pos in positions:
            entry_price = float(pos.entry_price)
            size = float(pos.size)
            notional = float(pos.notional_usd)

            # Calculate costs
            fee_cost = notional * (fee_bps / 10000.0)
            slippage_cost = notional * (slippage_bps / 10000.0)
            total_cost = fee_cost + slippage_cost

            # Simulate trade outcome (simplified: random win/loss based on stop/target)
            stop_loss = float(pos.stop_loss)
            take_profit = float(pos.take_profit)

            # Use ATR to determine likely outcome (wider stop = higher win rate)
            stop_distance = abs(entry_price - stop_loss)
            target_distance = abs(take_profit - entry_price)
            r_r_ratio = target_distance / stop_distance if stop_distance > 0 else 1.0

            # Simplified: assume win rate based on R:R (better R:R = lower win rate)
            base_win_rate = 0.50
            win_rate_adj = max(0.3, min(0.7, base_win_rate - (r_r_ratio - 1.5) * 0.1))
            is_win = np.random.random() < win_rate_adj

            if is_win:
                pnl = target_distance * size - total_cost
            else:
                pnl = -stop_distance * size - total_cost

            # Update capital
            capital += pnl

            # Track trade
            trades.append({
                'timestamp': df_current.iloc[-1]['timestamp'],
                'side': pos.side,
                'entry': entry_price,
                'exit': take_profit if is_win else stop_loss,
                'size': size,
                'pnl': pnl,
                'is_win': is_win,
                'notional': notional,
                'fee': total_cost,
            })

            # Update equity curve
            equity_curve.append(capital)

            # Track max drawdown
            if capital > max_equity:
                max_equity = capital
            dd_pct = ((max_equity - capital) / max_equity) * 100.0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            logger.debug(
                f"Trade #{len(trades)}: {pos.side} @ ${entry_price:.2f}, "
                f"PnL=${pnl:.2f}, Capital=${capital:.2f}"
            )

    # Calculate metrics
    period_days = (df_5m_features.iloc[-1]['timestamp'] - df_5m_features.iloc[0]['timestamp']).days

    if len(trades) == 0:
        logger.warning(f"Debug stats:")
        logger.warning(f"  Total 1m bars: {len(df_5m)}")
        logger.warning(f"  Total 5m bars: {len(df_5m_features)}")
        logger.warning(f"  should_trade() rejections: {should_trade_rejects}")
        logger.warning(f"  generate_signals() empty: {no_signal_count}")
        logger.warning(f"  Trades executed: {trade_count}")
        logger.warning("No trades generated!")
        return {
            'total_return_pct': 0.0,
            'profit_factor': 0.0,
            'max_dd_pct': 0.0,
            'sharpe_ratio': 0.0,
            'win_rate_pct': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'gross_profit': 0.0,
            'gross_loss': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'final_capital': initial_capital,
            'period_days': period_days,
            'status': 'NO_TRADES',
        }

    trades_df = pd.DataFrame(trades)
    winning_trades = trades_df[trades_df['is_win'] == True]
    losing_trades = trades_df[trades_df['is_win'] == False]

    total_return_pct = ((capital - initial_capital) / initial_capital) * 100.0
    win_rate_pct = (len(winning_trades) / len(trades)) * 100.0

    gross_profit = winning_trades['pnl'].sum() if len(winning_trades) > 0 else 0.0
    gross_loss = abs(losing_trades['pnl'].sum()) if len(losing_trades) > 0 else 0.01
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    # Calculate Sharpe (simplified)
    returns = trades_df['pnl'] / trades_df['notional']
    sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(len(trades)) if returns.std() > 0 else 0.0

    # Determine status
    if profit_factor >= 1.35 and sharpe_ratio >= 1.2 and max_dd_pct <= 12.0:
        status = "PASS"
    elif max_dd_pct > 20.0:
        status = "FAIL_DD"
    elif profit_factor < 1.0:
        status = "FAIL_PF"
    else:
        status = "MARGINAL"

    return {
        'total_return_pct': total_return_pct,
        'profit_factor': profit_factor,
        'max_dd_pct': max_dd_pct,
        'sharpe_ratio': sharpe_ratio,
        'win_rate_pct': win_rate_pct,
        'total_trades': len(trades),
        'winning_trades': len(winning_trades),
        'losing_trades': len(losing_trades),
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'avg_win': winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0.0,
        'avg_loss': losing_trades['pnl'].mean() if len(losing_trades) > 0 else 0.0,
        'final_capital': capital,
        'period_days': period_days,
        'status': status,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Run bar reaction strategy backtest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/bar_reaction_5m_aggressive.yaml"),
        help="Strategy config file (default: config/bar_reaction_5m_aggressive.yaml)"
    )

    parser.add_argument(
        "--lookback",
        type=int,
        default=180,
        help="Lookback period in days (default: 180)"
    )

    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Initial capital in USD (default: 10000)"
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file for results"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    logger.info("="*80)
    logger.info("BAR REACTION BACKTEST")
    logger.info("="*80)
    logger.info(f"Config: {args.config}")
    logger.info(f"Lookback: {args.lookback} days")
    logger.info(f"Capital: ${args.capital:.2f}")
    logger.info("")

    # Load config
    try:
        config = load_yaml_config(args.config)
        strat_config = config.get('strategy', {})
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)

    # Create strategy
    strategy = BarReaction5mStrategy(
        mode=strat_config.get('mode', 'trend'),
        trigger_mode=strat_config.get('trigger_mode', 'open_to_close'),
        trigger_bps_up=strat_config.get('trigger_bps_up', 12.0),
        trigger_bps_down=strat_config.get('trigger_bps_down', 12.0),
        min_atr_pct=strat_config.get('min_atr_pct', 0.25),
        max_atr_pct=strat_config.get('max_atr_pct', 3.0),
        atr_window=strat_config.get('atr_window', 14),
        sl_atr=strat_config.get('sl_atr', 0.6),
        tp1_atr=strat_config.get('tp1_atr', 1.0),
        tp2_atr=strat_config.get('tp2_atr', 1.8),
        risk_per_trade_pct=strat_config.get('risk_per_trade_pct', 0.6),
        min_position_usd=strat_config.get('min_position_usd', 0.0),
        max_position_usd=strat_config.get('max_position_usd', 100000.0),
        maker_only=strat_config.get('maker_only', True),
        spread_bps_cap=strat_config.get('spread_bps_cap', 8.0),
        enable_extreme_fade=strat_config.get('enable_extreme_fade', False),
        extreme_bps_threshold=strat_config.get('extreme_bps_threshold', 35.0),
        mean_revert_size_factor=strat_config.get('mean_revert_size_factor', 0.5),
    )

    logger.info("Strategy initialized with config:")
    logger.info(f"  Mode: {strategy.mode}")
    logger.info(f"  Trigger: {strategy.trigger_bps_up} bps")
    logger.info(f"  ATR range: {strategy.min_atr_pct}% - {strategy.max_atr_pct}%")
    logger.info(f"  Stop: {strategy.sl_atr}x ATR")
    logger.info(f"  Targets: TP1={strategy.tp1_atr}x, TP2={strategy.tp2_atr}x ATR")
    logger.info(f"  Risk/trade: {strategy.risk_per_trade_pct}%")
    logger.info(f"  Position limits: ${strategy.min_position_usd} - ${strategy.max_position_usd}")
    logger.info("")

    # Generate data
    logger.info("Generating synthetic 1m OHLCV data (will roll up to 5m)...")
    df_5m = generate_synthetic_ohlcv(
        pair="BTC/USD",
        timeframe_minutes=1,  # Generates 1m bars (rolled up to 5m by strategy)
        lookback_days=args.lookback,
        seed=42,
    )
    logger.info(f"Generated {len(df_5m)} bars")
    logger.info(f"Price range: ${df_5m['low'].min():.2f} - ${df_5m['high'].max():.2f}")
    logger.info("")

    # Run backtest
    logger.info("Running backtest...")
    results = run_simple_backtest(
        strategy=strategy,
        df_5m=df_5m,
        initial_capital=args.capital,
        fee_bps=config.get('backtest', {}).get('maker_fee_bps', 16.0),
        slippage_bps=config.get('backtest', {}).get('slippage_bps', 2.0),
    )

    # Print results
    logger.info("")
    logger.info("="*80)
    logger.info("RESULTS")
    logger.info("="*80)
    logger.info(f"Status: {results['status']}")
    logger.info(f"Total Return: {results['total_return_pct']:.2f}%")
    logger.info(f"Profit Factor: {results['profit_factor']:.2f}")
    logger.info(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    logger.info(f"Max Drawdown: {results['max_dd_pct']:.2f}%")
    logger.info(f"Win Rate: {results['win_rate_pct']:.2f}%")
    logger.info(f"Total Trades: {results['total_trades']}")
    logger.info(f"  Winners: {results['winning_trades']}")
    logger.info(f"  Losers: {results['losing_trades']}")
    logger.info(f"Avg Win: ${results['avg_win']:.2f}")
    logger.info(f"Avg Loss: ${results['avg_loss']:.2f}")
    logger.info(f"Final Capital: ${results['final_capital']:.2f}")
    logger.info("="*80)

    # Save results
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results saved to: {args.output}")

    # Exit code based on status
    if results['status'] == "PASS":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
