#!/usr/bin/env python3
"""
Crypto AI Bot - Simple Backtest Entrypoint
B2: CSV caching, multiple pairs, flexible CLI
B3: Standardized outputs (summary.csv, trades, equity, readme)
B4: Realistic cost model with maker/taker fees, slippage, risk management

Usage:
    python scripts/run_backtest.py --strategy scalper --pairs "BTC/USD" \\
        --timeframe 1h --lookback 180d --sl_bps 25 --tp_bps 35 \\
        --maker_bps 16 --taker_bps 26 --slippage_bps 2 --risk_per_trade_pct 1.0
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import ccxt

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backtesting.engine import BacktestEngine, BacktestConfig
from backtesting.metrics import BacktestResults
from backtesting.bar_reaction_engine import (
    BarReactionBacktestEngine,
    BarReactionBacktestConfig,
)

logger = logging.getLogger(__name__)


# --- Constants ---
CACHE_DIR = project_root / "data" / "cache"
REPORTS_DIR = project_root / "reports"
EXCHANGE = "kraken"  # Default exchange


# --- Data Loading with CSV Caching ---


def get_cache_path(symbol: str, timeframe: str, start_date: str, end_date: str) -> Path:
    """
    Generate cache file path for OHLCV data.

    Args:
        symbol: Trading pair (e.g., BTC/USD)
        timeframe: Candle timeframe (1m, 5m, 1h, etc.)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        Path to cache CSV file
    """
    # Sanitize symbol for filename
    symbol_safe = symbol.replace("/", "_")
    filename = f"{symbol_safe}_{timeframe}_{start_date}_{end_date}.csv"
    return CACHE_DIR / filename


def load_cached_ohlcv(cache_path: Path) -> Optional[pd.DataFrame]:
    """
    Load OHLCV data from CSV cache.

    Args:
        cache_path: Path to cache file

    Returns:
        DataFrame if cache exists and is valid, None otherwise
    """
    if not cache_path.exists():
        logger.debug(f"Cache miss: {cache_path.name}")
        return None

    try:
        df = pd.read_csv(cache_path, parse_dates=["timestamp"])
        logger.info(f"✓ Loaded {len(df)} candles from cache: {cache_path.name}")
        return df
    except Exception as e:
        logger.warning(f"Cache read error: {e}")
        return None


def save_ohlcv_cache(df: pd.DataFrame, cache_path: Path) -> None:
    """
    Save OHLCV data to CSV cache.

    Args:
        df: OHLCV DataFrame
        cache_path: Path to save cache
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path, index=False)
    logger.info(f"✓ Cached {len(df)} candles to: {cache_path.name}")


def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    exchange_name: str = EXCHANGE,
) -> pd.DataFrame:
    """
    Fetch OHLCV data with CSV caching.

    Prefer cached local CSV; else fetch via ccxt.

    Args:
        symbol: Trading pair (e.g., BTC/USD)
        timeframe: Candle timeframe (1m, 5m, 1h, etc.)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        exchange_name: Exchange name (default: kraken)

    Returns:
        DataFrame with OHLCV data
    """
    # Check cache first
    cache_path = get_cache_path(symbol, timeframe, start_date, end_date)
    cached_df = load_cached_ohlcv(cache_path)

    if cached_df is not None:
        return cached_df

    # Fetch from exchange
    logger.info(f"Fetching {symbol} {timeframe} from {exchange_name}...")

    exchange = getattr(ccxt, exchange_name)()
    exchange.enableRateLimit = True

    # Convert dates to timestamps
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
    end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp() * 1000)

    all_candles = []
    current_ts = start_ts
    limit = 1000  # Max per request

    while current_ts < end_ts:
        try:
            candles = exchange.fetch_ohlcv(
                symbol,
                timeframe,
                since=current_ts,
                limit=limit,
            )

            if not candles:
                break

            all_candles.extend(candles)
            current_ts = candles[-1][0] + 1

            logger.debug(f"  Fetched {len(candles)} candles (total: {len(all_candles)})")

            if current_ts >= end_ts:
                break

        except Exception as e:
            logger.error(f"Fetch error: {e}")
            break

    # Convert to DataFrame
    df = pd.DataFrame(
        all_candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"]
    )

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")

    # Filter to exact date range
    df = df[
        (df["timestamp"] >= start_date) &
        (df["timestamp"] <= end_date)
    ]

    logger.info(f"✓ Fetched {len(df)} candles for {symbol} from {exchange_name}")

    # Save to cache
    save_ohlcv_cache(df, cache_path)

    return df


# --- CLI & Main Logic ---


def parse_lookback(lookback_str: str) -> timedelta:
    """
    Parse lookback string (e.g., '180d', '7d', '1y') to timedelta.

    Args:
        lookback_str: Lookback string (e.g., '180d')

    Returns:
        timedelta object
    """
    if lookback_str.endswith("d"):
        days = int(lookback_str[:-1])
        return timedelta(days=days)
    elif lookback_str.endswith("w"):
        weeks = int(lookback_str[:-1])
        return timedelta(weeks=weeks)
    elif lookback_str.endswith("m"):
        months = int(lookback_str[:-1])
        return timedelta(days=months * 30)  # Approximate
    elif lookback_str.endswith("y"):
        years = int(lookback_str[:-1])
        return timedelta(days=years * 365)
    else:
        raise ValueError(f"Invalid lookback format: {lookback_str}")


def bps_to_pct(bps: int) -> float:
    """Convert basis points to percentage (0.01 = 1%)."""
    return bps / 10000


def load_bar_reaction_config(yaml_path: Optional[Path] = None) -> dict:
    """
    Load bar_reaction_5m configuration from YAML.

    Args:
        yaml_path: Path to YAML config file (default: config/bar_reaction_5m.yaml)

    Returns:
        Dict with strategy and backtest configuration
    """
    if yaml_path is None:
        yaml_path = project_root / "config" / "bar_reaction_5m.yaml"

    if not yaml_path.exists():
        raise FileNotFoundError(f"Bar reaction config not found: {yaml_path}")

    import yaml
    with open(yaml_path, "r") as f:
        config = yaml.safe_load(f)

    logger.info(f"Loaded bar_reaction_5m config from {yaml_path.name}")
    return config


# --- Standardized Output Functions (B3) ---


def save_summary_csv(
    results: BacktestResults,
    strategy: str,
    pair: str,
    timeframe: str,
    run_timestamp: str,
) -> None:
    """
    Append backtest summary to reports/backtest_summary.csv.

    Columns: run_ts, strategy, pair, timeframe, trades, win_rate, profit_factor,
             total_return_pct, cagr_pct, avg_trade_pct, max_dd_pct, sharpe, sortino, exposure_pct
    """
    summary_path = REPORTS_DIR / "backtest_summary.csv"

    # Calculate additional metrics
    closed_trades = [t for t in results.trades if t.status in ["closed", "stopped", "stop_loss", "take_profit", "end_of_backtest"]]
    avg_trade_pct = (
        sum(t.pnl_pct for t in closed_trades if t.pnl_pct) / len(closed_trades)
        if closed_trades else 0.0
    )

    # Estimate exposure (rough: total trade duration / total backtest duration)
    if closed_trades and results.timestamps is not None and len(results.timestamps) > 0:
        total_duration = (results.timestamps.iloc[-1] - results.timestamps.iloc[0]).total_seconds()
        trade_duration = sum(
            (t.exit_time - t.entry_time).total_seconds()
            for t in closed_trades if t.exit_time
        )
        exposure_pct = (trade_duration / total_duration * 100) if total_duration > 0 else 0.0
    else:
        exposure_pct = 0.0

    # Build row
    row = {
        "run_ts": run_timestamp,
        "strategy": strategy,
        "pair": pair,
        "timeframe": timeframe,
        "trades": results.total_trades,
        "win_rate": round(results.win_rate_pct, 2),
        "profit_factor": round(results.profit_factor, 2),
        "total_return_pct": round(results.total_return_pct, 2),
        "cagr_pct": round(results.annualized_return_pct, 2),
        "avg_trade_pct": round(avg_trade_pct, 2),
        "max_dd_pct": round(abs(results.max_drawdown_pct), 2),
        "sharpe": round(results.sharpe_ratio, 2),
        "sortino": round(results.sortino_ratio, 2),
        "exposure_pct": round(exposure_pct, 2),
    }

    # Append to CSV (create with header if doesn't exist)
    df_row = pd.DataFrame([row])

    if summary_path.exists():
        df_row.to_csv(summary_path, mode="a", header=False, index=False)
    else:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        df_row.to_csv(summary_path, mode="w", header=True, index=False)

    logger.info(f"✓ Appended to backtest_summary.csv")


def save_trades_csv(
    results: BacktestResults,
    strategy: str,
    pair: str,
    timeframe: str,
) -> None:
    """
    Save detailed trade log to reports/trades_{strategy}_{pair}_{tf}.csv.

    Columns: entry_time, exit_time, side, entry_price, exit_price, quantity,
             pnl_pct, pnl_usd, status
    """
    pair_safe = pair.replace("/", "_")
    trades_path = REPORTS_DIR / f"trades_{strategy}_{pair_safe}_{timeframe}.csv"

    closed_trades = [t for t in results.trades if t.exit_time is not None]

    if not closed_trades:
        logger.warning(f"No closed trades to save for {pair}")
        return

    trades_data = []
    for trade in closed_trades:
        trades_data.append({
            "entry_time": trade.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
            "exit_time": trade.exit_time.strftime("%Y-%m-%d %H:%M:%S") if trade.exit_time else "",
            "side": trade.side,
            "entry_price": round(trade.entry_price, 2),
            "exit_price": round(trade.exit_price, 2) if trade.exit_price else 0.0,
            "quantity": round(trade.quantity, 6),
            "pnl_pct": round(trade.pnl_pct, 2) if trade.pnl_pct else 0.0,
            "pnl_usd": round(trade.pnl, 2) if trade.pnl else 0.0,
            "status": trade.status,
        })

    df_trades = pd.DataFrame(trades_data)
    trades_path.parent.mkdir(parents=True, exist_ok=True)
    df_trades.to_csv(trades_path, index=False)

    logger.info(f"✓ Saved {len(closed_trades)} trades to {trades_path.name}")


def save_equity_json(
    results: BacktestResults,
    strategy: str,
    pair: str,
    timeframe: str,
) -> None:
    """
    Save equity curve to reports/equity_{strategy}_{pair}_{tf}.json.

    Format: [{"timestamp": "2024-01-01 00:00:00", "equity": 10000}, ...]
    """
    pair_safe = pair.replace("/", "_")
    equity_path = REPORTS_DIR / f"equity_{strategy}_{pair_safe}_{timeframe}.json"

    equity_data = []
    for ts, equity in zip(results.timestamps, results.equity_curve):
        equity_data.append({
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "equity": round(equity, 2),
        })

    import json
    equity_path.parent.mkdir(parents=True, exist_ok=True)

    with open(equity_path, "w") as f:
        json.dump(equity_data, f, indent=2)

    logger.info(f"✓ Saved equity curve to {equity_path.name}")


def append_readme(
    results: BacktestResults,
    strategy: str,
    pair: str,
    timeframe: str,
    run_timestamp: str,
    start_date: str,
    end_date: str,
) -> None:
    """
    Append human-readable summary to reports/backtest_readme.md.
    """
    readme_path = REPORTS_DIR / "backtest_readme.md"

    # Build markdown summary
    status_emoji = "✅" if results.total_return_pct > 0 else "❌"
    risk_grade = (
        "A" if results.sharpe_ratio > 2.0 else
        "B" if results.sharpe_ratio > 1.0 else
        "C" if results.sharpe_ratio > 0.5 else
        "D"
    )

    summary = f"""
---

## {status_emoji} {strategy.upper()} | {pair} | {timeframe} | {run_timestamp}

**Period:** {start_date} to {end_date}

**Performance:**
- Total Return: {results.total_return_pct:+.2f}%
- CAGR: {results.annualized_return_pct:+.2f}%
- Max Drawdown: {abs(results.max_drawdown_pct):.2f}%

**Risk Metrics:**
- Sharpe Ratio: {results.sharpe_ratio:.2f} (Grade: {risk_grade})
- Sortino Ratio: {results.sortino_ratio:.2f}
- Volatility: {results.volatility_annualized_pct:.2f}%

**Trade Stats:**
- Total Trades: {results.total_trades}
- Win Rate: {results.win_rate_pct:.1f}%
- Profit Factor: {results.profit_factor:.2f}
- Avg Win: ${results.avg_win:,.2f} | Avg Loss: ${results.avg_loss:,.2f}

**Files:**
- Trades: `trades_{strategy}_{pair.replace("/", "_")}_{timeframe}.csv`
- Equity: `equity_{strategy}_{pair.replace("/", "_")}_{timeframe}.json`

"""

    # Create or append
    if not readme_path.exists():
        readme_path.parent.mkdir(parents=True, exist_ok=True)
        with open(readme_path, "w") as f:
            f.write(f"# Crypto AI Bot — Backtest Results\n\n")
            f.write(f"Generated by `scripts/run_backtest.py`\n")
            f.write(f"All reports are in `/reports` directory.\n")

    with open(readme_path, "a") as f:
        f.write(summary)

    logger.info(f"✓ Appended to backtest_readme.md")


def save_config_json(
    strategy: str,
    pair: str,
    timeframe: str,
    config_params: dict,
) -> None:
    """
    Save backtest configuration as sidecar JSON (B4).

    Args:
        strategy: Strategy name
        pair: Trading pair
        timeframe: Candle timeframe
        config_params: Dict of all configuration parameters
    """
    pair_safe = pair.replace("/", "_")
    config_path = REPORTS_DIR / f"config_{strategy}_{pair_safe}_{timeframe}.json"

    import json
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        json.dump(config_params, f, indent=2)

    logger.info(f"✓ Saved config to {config_path.name}")


def run_bar_reaction_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    capital: float,
    yaml_config: dict,
) -> tuple[BacktestResults, dict]:
    """
    Run backtest for bar_reaction_5m strategy.

    Args:
        symbol: Trading pair
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        capital: Initial capital
        yaml_config: Loaded YAML configuration

    Returns:
        Tuple of (BacktestResults, config_dict)
    """
    logger.info("=" * 70)
    logger.info(f"BAR REACTION 5M BACKTEST: {symbol}")
    logger.info("=" * 70)

    # Extract config
    strategy_cfg = yaml_config["strategy"]
    backtest_cfg = yaml_config["backtest"]

    # Load data (1m for rollup to 5m)
    # TEMP WORKAROUND: Try 1m first, fall back to 5m if insufficient
    data = fetch_ohlcv(symbol, "1m", start_date, end_date)

    if len(data) < 500:
        logger.warning(f"⚠️  Insufficient 1m data ({len(data)} candles). Falling back to 5m data (less accurate fill simulation)")
        # Fetch 5m data instead
        data = fetch_ohlcv(symbol, "5m", start_date, end_date)
        if len(data) < 100:
            raise ValueError(f"Insufficient 5m data: {len(data)} candles, need at least 100")

    # Configure backtest
    config = BarReactionBacktestConfig(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_capital=capital,
        # Strategy params
        mode=strategy_cfg["mode"],
        trigger_mode=strategy_cfg["trigger_mode"],
        trigger_bps_up=strategy_cfg["trigger_bps_up"],
        trigger_bps_down=strategy_cfg["trigger_bps_down"],
        min_atr_pct=strategy_cfg["min_atr_pct"],
        max_atr_pct=strategy_cfg["max_atr_pct"],
        atr_window=strategy_cfg["atr_window"],
        sl_atr=strategy_cfg["sl_atr"],
        tp1_atr=strategy_cfg["tp1_atr"],
        tp2_atr=strategy_cfg["tp2_atr"],
        risk_per_trade_pct=strategy_cfg["risk_per_trade_pct"],
        maker_only=strategy_cfg["maker_only"],
        spread_bps_cap=strategy_cfg["spread_bps_cap"],
        # Cost model
        maker_fee_bps=backtest_cfg["maker_fee_bps"],
        slippage_bps=backtest_cfg["slippage_bps"],
        # Fill model
        queue_bars=backtest_cfg["queue_bars"],
    )

    # Build config dict for tracking
    config_dict = {
        "symbol": symbol,
        "strategy": "bar_reaction_5m",
        "timeframe": "5m",
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": capital,
        **strategy_cfg,
        **backtest_cfg,
    }

    logger.info(f"Strategy Config:")
    logger.info(f"  Mode: {config.mode}")
    logger.info(f"  Trigger: {config.trigger_mode}")
    logger.info(f"  Trigger thresholds: +{config.trigger_bps_up}bps / -{config.trigger_bps_down}bps")
    logger.info(f"  ATR range: {config.min_atr_pct:.2f}% - {config.max_atr_pct:.2f}%")
    logger.info(f"  ATR SL/TP: {config.sl_atr}x / {config.tp1_atr}x / {config.tp2_atr}x")
    logger.info(f"  Risk per trade: {config.risk_per_trade_pct}%")
    logger.info(f"Cost/Fill Model:")
    logger.info(f"  Maker fee: {config.maker_fee_bps}bps | Slippage: {config.slippage_bps}bps")
    logger.info(f"  Queue bars: {config.queue_bars}")

    # Run backtest
    engine = BarReactionBacktestEngine(config)
    results = engine.run(data)

    return results, config_dict


def run_single_backtest(
    symbol: str,
    strategy: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    sl_bps: int,
    tp_bps: int,
    maker_bps: int,
    taker_bps: int,
    slippage_bps: int,
    spread_bps_cap: int,
    overnight_fee_bps: int,
    risk_per_trade_pct: float,
    capital: float,
) -> tuple[BacktestResults, dict]:
    """
    Run backtest for a single symbol with realistic cost model (B4).

    Args:
        symbol: Trading pair
        strategy: Strategy name (scalper, momentum, etc.)
        timeframe: Candle timeframe
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        sl_bps: Stop loss in basis points
        tp_bps: Take profit in basis points
        maker_bps: Maker fee in basis points
        taker_bps: Taker fee in basis points
        slippage_bps: Slippage in basis points
        spread_bps_cap: Spread cap in basis points
        overnight_fee_bps: Overnight funding fee in basis points
        risk_per_trade_pct: Risk per trade as % of capital
        capital: Initial capital

    Returns:
        Tuple of (BacktestResults, config_dict)
    """
    logger.info("=" * 70)
    logger.info(f"BACKTEST: {symbol} | {strategy} | {timeframe}")
    logger.info("=" * 70)

    # Load data
    data = fetch_ohlcv(symbol, timeframe, start_date, end_date)

    if len(data) < 300:
        raise ValueError(f"Insufficient data: {len(data)} candles, need at least 300")

    # Calculate effective position size from risk
    # Using risk_per_trade_pct as position size (conservative approach)
    position_size_pct = risk_per_trade_pct / 100.0

    # Use taker fee as default (most trades will be taker)
    # Could be enhanced to model maker/taker ratio
    effective_commission_pct = bps_to_pct(taker_bps)

    # Configure backtest
    config = BacktestConfig(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        initial_capital=capital,
        timeframe=timeframe,
        position_size_pct=position_size_pct,
        max_positions=1,
        stop_loss_pct=bps_to_pct(sl_bps),
        take_profit_pct=bps_to_pct(tp_bps),
        commission_pct=effective_commission_pct,
        slippage_pct=bps_to_pct(slippage_bps),
    )

    # Build config dict for tracking (B4)
    config_dict = {
        "symbol": symbol,
        "strategy": strategy,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "initial_capital": capital,
        "risk_per_trade_pct": risk_per_trade_pct,
        "position_size_pct": position_size_pct * 100,  # Convert back to %
        "stop_loss_bps": sl_bps,
        "take_profit_bps": tp_bps,
        "maker_fee_bps": maker_bps,
        "taker_fee_bps": taker_bps,
        "effective_fee_bps": taker_bps,  # Using taker as default
        "slippage_bps": slippage_bps,
        "spread_cap_bps": spread_bps_cap,
        "overnight_fee_bps": overnight_fee_bps,
        "max_positions": 1,
    }

    logger.info(f"Risk/Cost Config:")
    logger.info(f"  Risk per trade: {risk_per_trade_pct}% → Position size: {position_size_pct*100:.2f}%")
    logger.info(f"  SL: {sl_bps}bps | TP: {tp_bps}bps")
    logger.info(f"  Maker: {maker_bps}bps | Taker: {taker_bps}bps | Slippage: {slippage_bps}bps")
    logger.info(f"  Spread cap: {spread_bps_cap}bps | Overnight: {overnight_fee_bps}bps")

    # Run backtest
    engine = BacktestEngine(config)
    results = engine.run(data)

    return results, config_dict


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Crypto AI Bot Simple Backtest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single pair scalper backtest with realistic costs (B4)
  python scripts/run_backtest.py --strategy scalper --pairs "BTC/USD" \\
      --timeframe 1h --lookback 180d --sl_bps 25 --tp_bps 35 \\
      --maker_bps 16 --taker_bps 26 --slippage_bps 2 --risk_per_trade_pct 1.0

  # Multi-pair momentum with aggressive risk
  python scripts/run_backtest.py --strategy momentum --pairs "BTC/USD,ETH/USD" \\
      --timeframe 1h --lookback 90d --sl_bps 30 --tp_bps 50 \\
      --taker_bps 26 --slippage_bps 2 --risk_per_trade_pct 2.0 --capital 50000

  # Conservative backtest with minimal costs
  python scripts/run_backtest.py --strategy breakout --pairs "BTC/USD" \\
      --timeframe 4h --lookback 1y --maker_bps 10 --taker_bps 20 \\
      --slippage_bps 1 --risk_per_trade_pct 0.5
        """,
    )

    parser.add_argument(
        "--strategy",
        type=str,
        default="scalper",
        choices=["scalper", "momentum", "mean_reversion", "breakout", "bar_reaction_5m"],
        help="Strategy to backtest (default: scalper)",
    )

    parser.add_argument(
        "--pairs",
        type=str,
        required=True,
        help='Trading pairs (comma-separated, e.g., "BTC/USD,ETH/USD")',
    )

    parser.add_argument(
        "--timeframe",
        type=str,
        default="1h",
        choices=["1m", "5m", "15m", "1h", "4h", "1d"],
        help="Candle timeframe (default: 1h)",
    )

    parser.add_argument(
        "--lookback",
        type=str,
        default="180d",
        help="Lookback period (e.g., 180d, 1y) (default: 180d)",
    )

    parser.add_argument(
        "--sl_bps",
        type=int,
        default=25,
        help="Stop loss in basis points (default: 25)",
    )

    parser.add_argument(
        "--tp_bps",
        type=int,
        default=35,
        help="Take profit in basis points (default: 35)",
    )

    # Cost & Slippage parameters (B4 - Realistic costs)
    parser.add_argument(
        "--maker_bps",
        type=int,
        default=16,
        help="Maker fee in basis points (default: 16)",
    )

    parser.add_argument(
        "--taker_bps",
        type=int,
        default=26,
        help="Taker fee in basis points (default: 26)",
    )

    parser.add_argument(
        "--slippage_bps",
        type=int,
        default=2,
        help="Slippage in basis points (default: 2)",
    )

    parser.add_argument(
        "--spread_bps_cap",
        type=int,
        default=10,
        help="Spread cap in basis points (default: 10)",
    )

    parser.add_argument(
        "--overnight_fee_bps",
        type=int,
        default=0,
        help="Overnight funding fee in basis points (default: 0)",
    )

    # Risk parameters
    parser.add_argument(
        "--risk_per_trade_pct",
        type=float,
        default=1.0,
        help="Risk per trade as percentage of capital (default: 1.0)",
    )

    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Initial capital in USD (default: 10000)",
    )

    parser.add_argument(
        "--mode",
        type=str,
        default="backtest",
        choices=["backtest", "live"],
        help="Execution mode (default: backtest). WARNING: live mode not implemented.",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    parser.add_argument(
        "--from-json",
        type=str,
        help="Load parameters from JSON file (e.g., reports/best_params.json)",
    )

    # ML Confidence Gate parameters (Step 7)
    parser.add_argument(
        "--ml",
        type=str,
        default=None,
        choices=["on", "off"],
        help="Override ML confidence gate enable/disable (default: use ml.yaml)",
    )

    parser.add_argument(
        "--min_alignment_confidence",
        type=float,
        default=None,
        help="Override minimum ML confidence threshold (default: use ml.yaml)",
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Step 7: Apply ML config overrides from CLI
    if args.ml is not None or args.min_alignment_confidence is not None:
        import yaml
        ml_config_path = project_root / "config" / "params" / "ml.yaml"

        # Load existing config
        if ml_config_path.exists():
            with open(ml_config_path) as f:
                ml_config = yaml.safe_load(f)
        else:
            ml_config = {
                "enabled": False,
                "min_alignment_confidence": 0.65,
                "seed": 42,
                "models": [
                    {"type": "logit", "enabled": True},
                    {"type": "tree", "enabled": True}
                ],
                "features": ["returns", "rsi", "adx", "slope"]
            }

        # Apply CLI overrides
        if args.ml is not None:
            ml_config["enabled"] = (args.ml == "on")
            logger.info(f"🔧 ML override: enabled={ml_config['enabled']}")

        if args.min_alignment_confidence is not None:
            ml_config["min_alignment_confidence"] = args.min_alignment_confidence
            logger.info(f"🔧 ML override: min_alignment_confidence={args.min_alignment_confidence}")

        # Write back to ml.yaml (temporary override for this backtest run)
        ml_config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ml_config_path, "w") as f:
            yaml.safe_dump(ml_config, f, default_flow_style=False)

        logger.info(f"✅ ML config updated: {ml_config_path}")

    # Load from JSON if specified
    if args.from_json:
        import json
        json_path = Path(args.from_json)

        if not json_path.exists():
            logger.error(f"JSON file not found: {json_path}")
            sys.exit(1)

        logger.info(f"Loading parameters from {json_path}")
        with open(json_path, "r") as f:
            params = json.load(f)

        # Override args with JSON params
        args.pairs = params["pair"]
        args.timeframe = params["timeframe"]
        args.risk_per_trade_pct = params["position_size_pct"]

        # Convert percentages back to bps for CLI consistency
        args.sl_bps = int(params["sl_pct"] * 100)
        args.tp_bps = int(params["tp2_pct"] * 100)
        args.maker_bps = params["maker_fee_bps"]
        args.taker_bps = params["maker_fee_bps"]  # Use maker for maker-only
        args.slippage_bps = params["slippage_bps"]

        logger.info(f"Loaded best params: {params['pair']} {params['timeframe']} "
                   f"(PF={params['profit_factor']:.2f}, Sharpe={params['sharpe_ratio']:.2f})")

    # Safety check
    if args.mode == "live":
        logger.error("⚠️  LIVE MODE NOT IMPLEMENTED. Use --mode backtest only.")
        sys.exit(1)

    # Parse lookback
    try:
        lookback_delta = parse_lookback(args.lookback)
        # Use current date minus 1 day to avoid incomplete candles
        end_date = datetime.now() - timedelta(days=1)
        start_date = end_date - lookback_delta

        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

    except ValueError as e:
        logger.error(f"Invalid lookback: {e}")
        sys.exit(1)

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(",")]

    logger.info("=" * 70)
    logger.info("CRYPTO AI BOT - BACKTESTING (B4 Realistic Costs)")
    logger.info("=" * 70)
    logger.info(f"Strategy: {args.strategy}")
    logger.info(f"Pairs: {', '.join(pairs)}")
    logger.info(f"Period: {start_date_str} to {end_date_str} ({args.lookback})")
    logger.info(f"Timeframe: {args.timeframe}")
    logger.info(f"Risk: {args.risk_per_trade_pct}% per trade | Capital: ${args.capital:,.0f}")
    logger.info(f"Costs: Maker={args.maker_bps}bps, Taker={args.taker_bps}bps, Slip={args.slippage_bps}bps")
    logger.info("")

    # Load bar_reaction_5m config if needed
    bar_reaction_yaml = None
    if args.strategy == "bar_reaction_5m":
        bar_reaction_yaml = load_bar_reaction_config()

    # Run backtests
    all_results = []

    for symbol in pairs:
        try:
            # Route to appropriate backtest engine
            if args.strategy == "bar_reaction_5m":
                results, config_dict = run_bar_reaction_backtest(
                    symbol=symbol,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    capital=args.capital,
                    yaml_config=bar_reaction_yaml,
                )
            else:
                results, config_dict = run_single_backtest(
                    symbol=symbol,
                    strategy=args.strategy,
                    timeframe=args.timeframe,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    sl_bps=args.sl_bps,
                    tp_bps=args.tp_bps,
                    maker_bps=args.maker_bps,
                    taker_bps=args.taker_bps,
                    slippage_bps=args.slippage_bps,
                    spread_bps_cap=args.spread_bps_cap,
                    overnight_fee_bps=args.overnight_fee_bps,
                    risk_per_trade_pct=args.risk_per_trade_pct,
                    capital=args.capital,
                )

            all_results.append((symbol, results))

            # Print results
            print(f"\n{'=' * 70}")
            print(f"RESULTS: {symbol}")
            print('=' * 70)
            results.print_summary()

            # Generate run timestamp
            run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Determine timeframe (use 5m for bar_reaction_5m, otherwise from args)
            timeframe = "5m" if args.strategy == "bar_reaction_5m" else args.timeframe

            # Save standardized outputs (B3) + config (B4)
            logger.info(f"\nSaving standardized outputs...")
            save_summary_csv(results, args.strategy, symbol, timeframe, run_timestamp)
            save_trades_csv(results, args.strategy, symbol, timeframe)
            save_equity_json(results, args.strategy, symbol, timeframe)
            save_config_json(args.strategy, symbol, timeframe, config_dict)
            append_readme(results, args.strategy, symbol, timeframe, run_timestamp, start_date_str, end_date_str)

        except Exception as e:
            logger.error(f"❌ Backtest failed for {symbol}: {e}")
            if args.debug:
                import traceback
                traceback.print_exc()

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print('=' * 70)

    if not all_results:
        logger.error("No successful backtests")
        sys.exit(1)

    for symbol, results in all_results:
        status = "✓ PROFITABLE" if results.total_return_pct > 0 else "✗ NOT PROFITABLE"
        print(f"{symbol:12} | Return: {results.total_return_pct:+7.2f}% | "
              f"Sharpe: {results.sharpe_ratio:6.2f} | Trades: {results.total_trades:4d} | {status}")

    print("")
    logger.info("✓ Backtesting complete. Reports saved to /reports")

    # Exit with success
    sys.exit(0)


if __name__ == "__main__":
    main()
