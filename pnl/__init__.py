"""
PnL Package - Rolling profit/loss tracking for crypto-ai-bot.

This package provides:
- Rolling PnL calculation with Redis persistence (pnl/rolling_pnl.py)
- Real-time equity curve tracking
- Both realized and unrealized PnL

Usage:
    from pnl.rolling_pnl import PnLTracker

    tracker = PnLTracker(redis_url=REDIS_URL, redis_cert_path=CERT_PATH)
    await tracker.connect()

    # Process trade fill
    await tracker.process_fill(fill_data)

    # Update mark-to-market PnL
    await tracker.update_mtm({"BTC/USD": 50000.0, ...})

    # Get current PnL
    pnl = await tracker.get_summary()
"""

from .rolling_pnl import PnLTracker, PnLSummary

__all__ = [
    "PnLTracker",
    "PnLSummary",
]
