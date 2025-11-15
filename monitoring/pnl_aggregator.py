#!/usr/bin/env python3
"""
PnL Aggregator Service - Crypto AI Bot

Consumes trade close events from Redis stream "trades:closed", accumulates
equity and daily PnL, and publishes aggregated snapshots to "pnl:equity".

Features:
- Idempotent and resumable (stores last processed ID)
- Day boundary detection with automatic daily PnL reset
- Optional Prometheus metrics exposure
- Memory-safe with bounded processing windows

Environment Variables:
    REDIS_URL - Redis connection string (default: redis://localhost:6379/0)
    START_EQUITY - Initial equity in USD (default: 10000.0)
    POLL_MS - Polling interval in milliseconds (default: 500)
    STATE_KEY - Redis key for last processed ID (default: pnl:agg:last_id)
    PNL_METRICS_PORT - Enable Prometheus metrics on port (default: disabled)
    USE_PANDAS - Enable pandas-based statistics (default: false)
    STATS_WINDOW_SIZE - Max trades to keep for stats (default: 5000, max: 5000)

Usage:
    python monitoring/pnl_aggregator.py
"""

import os
import sys
import time
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, Optional

try:
    import orjson
except ImportError:
    import json as orjson  # Fallback to stdlib json

try:
    import redis
except ImportError:
    print("ERROR: redis package not installed. Run: pip install redis")
    sys.exit(1)


# Optional Prometheus support
PROMETHEUS_ENABLED = False
try:
    from prometheus_client import Counter, Gauge, start_http_server

    PROMETHEUS_ENABLED = True
except ImportError:
    Counter = None  # type: ignore
    Gauge = None  # type: ignore
    start_http_server = None  # type: ignore

# Optional pandas support for statistics
PANDAS_ENABLED = False
try:
    import numpy as np
    import pandas as pd

    PANDAS_ENABLED = True
except ImportError:
    np = None  # type: ignore
    pd = None  # type: ignore


# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
START_EQUITY = float(os.getenv("START_EQUITY", "10000.0"))
POLL_MS = int(os.getenv("POLL_MS", "500"))
STATE_KEY = os.getenv("STATE_KEY", "pnl:agg:last_id")
PNL_METRICS_PORT = os.getenv("PNL_METRICS_PORT")
USE_PANDAS = os.getenv("USE_PANDAS", "false").lower() in ("true", "1", "yes")
STATS_WINDOW_SIZE = min(int(os.getenv("STATS_WINDOW_SIZE", "5000")), 5000)  # Max 5k

# Prometheus metrics (initialized if enabled)
metrics_equity: Optional[any] = None
metrics_daily_pnl: Optional[any] = None
metrics_daily_target: Optional[any] = None
metrics_rolling_equity: Optional[any] = None
metrics_win_rate_7d: Optional[any] = None
metrics_pf_30d: Optional[any] = None
metrics_trades_30d: Optional[any] = None
metrics_trades_total: Optional[any] = None

# Alert flags
metrics_drawdown_soft: Optional[any] = None
metrics_drawdown_hard: Optional[any] = None
metrics_loss_streak_active: Optional[any] = None


def _init_prometheus_metrics(port: int) -> None:
    """Initialize Prometheus metrics server with targets and alerts."""
    global metrics_equity, metrics_daily_pnl, metrics_daily_target
    global metrics_rolling_equity, metrics_win_rate_7d, metrics_pf_30d, metrics_trades_30d
    global metrics_trades_total
    global metrics_drawdown_soft, metrics_drawdown_hard, metrics_loss_streak_active

    if not PROMETHEUS_ENABLED:
        print("[WARN] Prometheus client not installed. Metrics disabled.")
        return

    try:
        # Core PnL metrics
        metrics_equity = Gauge("pnl_equity_usd", "Current account equity in USD")
        metrics_daily_pnl = Gauge("pnl_daily_usd", "Daily profit/loss in USD")
        metrics_daily_target = Gauge("pnl_daily_target_usd", "Daily PnL target based on CAGR path")

        # Rolling metrics
        metrics_rolling_equity = Gauge("pnl_rolling_equity_usd", "30-day rolling equity")
        metrics_win_rate_7d = Gauge("pnl_win_rate_7d", "7-day rolling win rate (0-1)")
        metrics_pf_30d = Gauge("pnl_profit_factor_30d", "30-day profit factor")
        metrics_trades_30d = Gauge("pnl_trades_30d", "Number of trades in last 30 days")

        # Trade counter
        metrics_trades_total = Counter("pnl_trades_total", "Total trades processed")

        # Alert flags (0=OK, 1=TRIGGERED)
        metrics_drawdown_soft = Gauge("alert_drawdown_soft", "Soft drawdown alert (4% daily DD)")
        metrics_drawdown_hard = Gauge("alert_drawdown_hard", "Hard drawdown alert (6% daily DD)")
        metrics_loss_streak_active = Gauge("alert_loss_streak", "Loss streak alert (3+ consecutive losses)")

        start_http_server(port)
        print(f"[OK] Prometheus metrics server started on port {port}")
        print(f"     Metrics: /metrics")
    except Exception as e:
        print(f"[WARN] Failed to start Prometheus metrics: {e}")


def _get_current_day_start_ms() -> int:
    """Get current UTC day start timestamp in milliseconds."""
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(day_start.timestamp() * 1000)


def _calculate_daily_target(equity: float, target_sharpe: float = 1.0, target_pf: float = 1.35) -> float:
    """
    Calculate daily PnL target based on target CAGR path.

    Target CAGR from Sharpe=1.0, PF=1.35:
    - Sharpe 1.0 with ~15% volatility → ~15% annual return
    - PF 1.35 suggests ~25% edge over costs
    - Conservative target: 12% CAGR (1% monthly, 0.033% daily)

    Args:
        equity: Current equity in USD
        target_sharpe: Target Sharpe ratio (default: 1.0)
        target_pf: Target profit factor (default: 1.35)

    Returns:
        Daily PnL target in USD
    """
    # Target CAGR: 12% annually = 1.12^(1/365) - 1 = 0.0309% daily
    daily_return_target = 0.000309  # 0.0309%
    return equity * daily_return_target


def _check_drawdown_alerts(equity: float, day_start_equity: float) -> tuple[bool, bool]:
    """
    Check if drawdown alerts should trigger.

    Args:
        equity: Current equity
        day_start_equity: Equity at start of day

    Returns:
        (soft_alert, hard_alert) tuple
            soft_alert: True if daily DD >= 4%
            hard_alert: True if daily DD >= 6%
    """
    daily_dd_pct = ((equity - day_start_equity) / day_start_equity) * 100 if day_start_equity > 0 else 0.0

    soft_alert = daily_dd_pct <= -4.0  # -4% or worse
    hard_alert = daily_dd_pct <= -6.0  # -6% or worse

    return soft_alert, hard_alert


def _check_loss_streak(trades_window: Deque[Dict], threshold: int = 3) -> bool:
    """
    Check if current loss streak meets threshold.

    Args:
        trades_window: Recent trades
        threshold: Number of consecutive losses to trigger (default: 3)

    Returns:
        True if loss streak >= threshold
    """
    if len(trades_window) < threshold:
        return False

    # Check last N trades
    recent_trades = list(trades_window)[-threshold:]

    # All losses?
    all_losses = all(t.get("pnl", 0) < 0 for t in recent_trades)

    return all_losses


def _publish_equity_point(
    client: redis.Redis, ts_ms: int, equity: float, daily_pnl: float
) -> None:
    """Publish equity snapshot to Redis stream and latest key."""
    snapshot = {
        "ts": ts_ms,
        "equity": equity,
        "daily_pnl": daily_pnl,
    }

    # Serialize
    if hasattr(orjson, "dumps"):
        json_bytes = orjson.dumps(snapshot)
    else:
        json_bytes = orjson.dumps(snapshot).encode("utf-8")

    # Publish to stream
    client.xadd("pnl:equity", {"json": json_bytes})

    # Update latest value
    client.set("pnl:equity:latest", json_bytes)


def _calculate_stats(trades_window: Deque[Dict]) -> Dict[str, float]:
    """
    Calculate trading statistics from a rolling window of trades.

    Args:
        trades_window: Deque of trade events with 'pnl' and 'ts' fields

    Returns:
        Dict with keys: win_rate, win_rate_7d, profit_factor_30d, trades_30d, max_drawdown, sharpe
    """
    if not trades_window or not PANDAS_ENABLED:
        return {
            "win_rate": 0.0,
            "win_rate_7d": 0.0,
            "profit_factor_30d": 0.0,
            "trades_30d": 0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
        }

    # Convert to DataFrame
    trades_list = list(trades_window)
    df = pd.DataFrame({
        "pnl": [t.get("pnl", 0.0) for t in trades_list],
        "ts": [t.get("ts", 0) for t in trades_list],
    })

    # Overall win rate
    wins = (df["pnl"] > 0).sum()
    total = len(df)
    win_rate = float(wins / total) if total > 0 else 0.0

    # 7-day rolling win rate
    now_ms = int(time.time() * 1000)
    seven_days_ms = 7 * 24 * 60 * 60 * 1000
    df_7d = df[df["ts"] >= (now_ms - seven_days_ms)]

    if len(df_7d) > 0:
        wins_7d = (df_7d["pnl"] > 0).sum()
        win_rate_7d = float(wins_7d / len(df_7d))
    else:
        win_rate_7d = 0.0

    # 30-day profit factor and trade count
    thirty_days_ms = 30 * 24 * 60 * 60 * 1000
    df_30d = df[df["ts"] >= (now_ms - thirty_days_ms)]

    if len(df_30d) > 0:
        gross_profit = df_30d[df_30d["pnl"] > 0]["pnl"].sum()
        gross_loss = abs(df_30d[df_30d["pnl"] < 0]["pnl"].sum())

        if gross_loss > 0:
            pf_30d = float(gross_profit / gross_loss)
        else:
            pf_30d = float(gross_profit) if gross_profit > 0 else 0.0

        trades_30d = len(df_30d)
    else:
        pf_30d = 0.0
        trades_30d = 0

    # Max drawdown (cumulative equity curve)
    cumulative = df["pnl"].cumsum()
    running_max = cumulative.cummax()
    drawdown = running_max - cumulative
    max_drawdown = float(drawdown.max()) if len(drawdown) > 0 else 0.0

    # Sharpe ratio (naive: mean / std)
    if len(df) > 1 and df["pnl"].std() > 0:
        sharpe = float(df["pnl"].mean() / df["pnl"].std())
    else:
        sharpe = 0.0

    return {
        "win_rate": round(win_rate, 4),
        "win_rate_7d": round(win_rate_7d, 4),
        "profit_factor_30d": round(pf_30d, 2),
        "trades_30d": trades_30d,
        "max_drawdown": round(max_drawdown, 2),
        "sharpe": round(sharpe, 4),
    }


def _publish_stats(client: redis.Redis, stats: Dict[str, float]) -> None:
    """Publish statistics to Redis keys and Prometheus metrics."""
    try:
        # Publish to Redis
        client.set("pnl:stats:win_rate", str(stats["win_rate"]))
        client.set("pnl:stats:win_rate_7d", str(stats["win_rate_7d"]))
        client.set("pnl:stats:profit_factor_30d", str(stats["profit_factor_30d"]))
        client.set("pnl:stats:trades_30d", str(stats["trades_30d"]))
        client.set("pnl:stats:max_drawdown", str(stats["max_drawdown"]))
        client.set("pnl:stats:sharpe", str(stats["sharpe"]))

        # Update Prometheus gauges
        if metrics_win_rate_7d:
            metrics_win_rate_7d.set(stats["win_rate_7d"])
        if metrics_pf_30d:
            metrics_pf_30d.set(stats["profit_factor_30d"])
        if metrics_trades_30d:
            metrics_trades_30d.set(stats["trades_30d"])
    except Exception as e:
        # Silent failure
        pass


def run_pnl_aggregator() -> None:
    """
    Run the PnL aggregator service.

    Continuously consumes trades from "trades:closed" stream, accumulates equity,
    detects day boundaries, and publishes aggregated PnL data.
    """
    print("=" * 60)
    print("PNL AGGREGATOR SERVICE")
    print("=" * 60)
    print(f"Redis URL: {REDIS_URL}")
    print(f"Start Equity: ${START_EQUITY:,.2f}")
    print(f"Poll Interval: {POLL_MS}ms")
    print(f"State Key: {STATE_KEY}")
    if USE_PANDAS and PANDAS_ENABLED:
        print(f"[INFO] Pandas Stats: ENABLED (window size: {STATS_WINDOW_SIZE})")
    elif USE_PANDAS and not PANDAS_ENABLED:
        print("[WARN] Pandas Stats: DISABLED (pandas not installed)")
    print("=" * 60)

    # Initialize Prometheus metrics if port specified
    if PNL_METRICS_PORT:
        try:
            port = int(PNL_METRICS_PORT)
            _init_prometheus_metrics(port)
        except ValueError:
            print(f"[WARN] Invalid PNL_METRICS_PORT: {PNL_METRICS_PORT}")

    # Connect to Redis
    try:
        client = redis.from_url(
            REDIS_URL,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        client.ping()
        print("[OK] Connected to Redis")
    except Exception as e:
        print(f"[ERROR] Failed to connect to Redis: {e}")
        sys.exit(1)

    # Initialize state
    equity = START_EQUITY
    day_start_equity = START_EQUITY
    current_day_start_ms = _get_current_day_start_ms()
    trades_processed = 0

    # Initialize trades window for statistics (memory-bounded)
    trades_window: Deque[Dict] = deque(maxlen=STATS_WINDOW_SIZE) if USE_PANDAS and PANDAS_ENABLED else deque()

    # Resume from last processed ID
    try:
        last_id_bytes = client.get(STATE_KEY)
        if last_id_bytes:
            last_id = last_id_bytes.decode("utf-8")
            print(f"[INFO] Resuming from last ID: {last_id}")
        else:
            last_id = "0-0"
            print(f"[INFO] Starting fresh from: {last_id}")
    except Exception as e:
        print(f"[WARN] Could not read state key: {e}")
        last_id = "0-0"

    # Try to restore equity from latest snapshot
    try:
        latest_bytes = client.get("pnl:equity:latest")
        if latest_bytes:
            if hasattr(orjson, "loads"):
                latest_data = orjson.loads(latest_bytes)
            else:
                latest_data = orjson.loads(latest_bytes.decode("utf-8"))

            equity = float(latest_data.get("equity", START_EQUITY))
            daily_pnl = float(latest_data.get("daily_pnl", 0.0))
            day_start_equity = equity - daily_pnl

            print(f"[INFO] Restored equity: ${equity:,.2f} (daily PnL: ${daily_pnl:,.2f})")
    except Exception as e:
        print(f"[WARN] Could not restore equity: {e}")

    # Update Prometheus gauges with initial values
    if metrics_equity:
        metrics_equity.set(equity)
    if metrics_daily_pnl:
        metrics_daily_pnl.set(equity - day_start_equity)

    print("\n[START] Starting aggregator loop...\n")

    # Main aggregation loop
    try:
        while True:
            try:
                # Read from stream (blocking with timeout)
                result = client.xread(
                    {"trades:closed": last_id},
                    count=200,
                    block=POLL_MS,
                )

                if not result:
                    # No new messages - continue polling
                    continue

                # Process messages
                stream_name, messages = result[0]

                for message_id, fields in messages:
                    # Decode message ID
                    msg_id = message_id.decode("utf-8") if isinstance(message_id, bytes) else message_id

                    # Parse event from 'json' field
                    try:
                        json_bytes = fields.get(b"json") or fields.get("json")
                        if not json_bytes:
                            print(f"[WARN] Skipping message {msg_id}: no 'json' field")
                            last_id = msg_id
                            continue

                        if hasattr(orjson, "loads"):
                            event = orjson.loads(json_bytes)
                        else:
                            if isinstance(json_bytes, bytes):
                                json_bytes = json_bytes.decode("utf-8")
                            event = orjson.loads(json_bytes)

                    except Exception as e:
                        print(f"[WARN] Failed to parse message {msg_id}: {e}")
                        last_id = msg_id
                        continue

                    # Extract PnL and timestamp
                    pnl = event.get("pnl")
                    ts_ms = event.get("ts")

                    if pnl is None or ts_ms is None:
                        print(f"[WARN] Skipping message {msg_id}: missing pnl or ts")
                        last_id = msg_id
                        continue

                    # Check for day boundary crossing
                    trade_day_start_ms = _get_current_day_start_ms()
                    if trade_day_start_ms > current_day_start_ms:
                        # Day crossed - reset daily PnL
                        print(
                            f"[DAY] Day boundary crossed! Resetting daily PnL. "
                            f"Previous: ${equity - day_start_equity:,.2f}"
                        )
                        day_start_equity = equity
                        current_day_start_ms = trade_day_start_ms

                    # Update equity
                    equity += float(pnl)
                    daily_pnl = equity - day_start_equity
                    trades_processed += 1

                    # Publish equity point
                    _publish_equity_point(client, ts_ms, equity, daily_pnl)

                    # Calculate daily target
                    daily_target = _calculate_daily_target(equity)

                    # Check alerts
                    soft_alert, hard_alert = _check_drawdown_alerts(equity, day_start_equity)
                    loss_streak = _check_loss_streak(trades_window) if USE_PANDAS and PANDAS_ENABLED else False

                    # Update Prometheus metrics
                    if metrics_equity:
                        metrics_equity.set(equity)
                    if metrics_daily_pnl:
                        metrics_daily_pnl.set(daily_pnl)
                    if metrics_daily_target:
                        metrics_daily_target.set(daily_target)
                    if metrics_rolling_equity:
                        metrics_rolling_equity.set(equity)  # Use current equity for now
                    if metrics_trades_total:
                        metrics_trades_total.inc()

                    # Update alert flags
                    if metrics_drawdown_soft:
                        metrics_drawdown_soft.set(1.0 if soft_alert else 0.0)
                    if metrics_drawdown_hard:
                        metrics_drawdown_hard.set(1.0 if hard_alert else 0.0)
                    if metrics_loss_streak_active:
                        metrics_loss_streak_active.set(1.0 if loss_streak else 0.0)

                    # Log alerts if triggered
                    if soft_alert:
                        print(f"  [ALERT] Soft drawdown: daily DD >= 4%")
                    if hard_alert:
                        print(f"  [ALERT] Hard drawdown: daily DD >= 6%")
                    if loss_streak:
                        print(f"  [ALERT] Loss streak: 3+ consecutive losses")

                    # Update last processed ID
                    last_id = msg_id

                    # Add to trades window for stats (if enabled)
                    if USE_PANDAS and PANDAS_ENABLED:
                        trades_window.append(event)

                    # Log progress
                    print(
                        f"[TRADE] Trade {trades_processed}: "
                        f"PnL ${pnl:+,.2f} → "
                        f"Equity ${equity:,.2f} "
                        f"(daily: ${daily_pnl:+,.2f})"
                    )

                # Calculate and publish stats (if enabled)
                if USE_PANDAS and PANDAS_ENABLED and len(trades_window) > 0:
                    stats = _calculate_stats(trades_window)
                    _publish_stats(client, stats)

                # Save checkpoint after processing batch
                client.set(STATE_KEY, last_id)

            except redis.ConnectionError as e:
                print(f"[WARN] Redis connection error: {e}")
                time.sleep(5)  # Wait before retry
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"[WARN] Error in aggregation loop: {e}")
                time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n[STOP] Shutdown requested...")
        print(f"[INFO] Final state:")
        print(f"   Equity: ${equity:,.2f}")
        print(f"   Daily PnL: ${equity - day_start_equity:+,.2f}")
        print(f"   Trades processed: {trades_processed}")
        print(f"   Last ID: {last_id}")

        # Save final state
        try:
            client.set(STATE_KEY, last_id)
            print("[OK] State saved successfully")
        except Exception as e:
            print(f"[WARN] Failed to save state: {e}")


if __name__ == "__main__":
    run_pnl_aggregator()
