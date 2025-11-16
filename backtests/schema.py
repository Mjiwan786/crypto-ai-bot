"""
backtests/schema.py - Per-Pair Backtest Export Schema

Pydantic models for TradingView-style per-pair backtest artifacts.
These JSON files are consumed by signals-api and signals-site for
interactive backtest visualizations.

Schema design goals:
- TradingView-compatible equity/PnL charts per pair
- Entry/exit markers for every trade
- Detailed trade table like TradingView's "List of trades"
- Separate from live PnL tracking
- Timezone-aware UTC timestamps
- Production-safe: works in Docker/Fly.io

Author: Crypto AI Bot Team
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# ENUMS
# =============================================================================

class TradeSide(str, Enum):
    """Trade direction"""
    LONG = "long"
    SHORT = "short"


class ExitReason(str, Enum):
    """Why a trade was closed"""
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TIME_EXIT = "time_exit"
    END_OF_BACKTEST = "end_of_backtest"
    SIGNAL_FLIP = "signal_flip"


# =============================================================================
# CORE MODELS
# =============================================================================

class EquityPoint(BaseModel):
    """
    Single point on the equity curve.

    Used to generate TradingView-style PnL charts per pair.

    Attributes:
        ts: Timestamp (ISO8601 UTC)
        equity: Total equity value (cash + positions)
        balance: Cash balance
        unrealized_pnl: Unrealized P&L from open positions (optional)
    """
    ts: datetime = Field(..., description="Timestamp in UTC")
    equity: float = Field(..., description="Total equity (cash + positions)")
    balance: Optional[float] = Field(None, description="Cash balance")
    unrealized_pnl: Optional[float] = Field(None, description="Unrealized P&L")

    @field_validator('ts')
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Ensure timestamp is timezone-aware UTC"""
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware (UTC)")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "ts": "2025-11-15T12:34:56.789000+00:00",
                "equity": 10250.50,
                "balance": 9500.00,
                "unrealized_pnl": 750.50
            }
        }


class Trade(BaseModel):
    """
    Single completed trade record.

    Displayed in TradingView-style trade table with entry/exit markers.

    Attributes:
        id: Trade ID (unique)
        ts_entry: Entry timestamp (UTC)
        ts_exit: Exit timestamp (UTC)
        side: Trade direction (long/short)
        entry_price: Entry price
        exit_price: Exit price
        size: Position size (in base currency)
        net_pnl: Net profit/loss (after fees)
        runup: Maximum favorable price movement during trade (optional)
        drawdown: Maximum adverse price movement during trade (optional)
        cumulative_pnl: Cumulative P&L after this trade (optional)
        signal: Strategy/signal that generated trade (optional)
        exit_reason: Why the trade was closed (optional)
    """
    id: int = Field(..., description="Trade ID (sequential)")
    ts_entry: datetime = Field(..., description="Entry timestamp (UTC)")
    ts_exit: datetime = Field(..., description="Exit timestamp (UTC)")
    side: TradeSide = Field(..., description="Trade direction")
    entry_price: float = Field(..., gt=0, description="Entry price")
    exit_price: float = Field(..., gt=0, description="Exit price")
    size: float = Field(..., gt=0, description="Position size")
    net_pnl: float = Field(..., description="Net P&L (after fees)")
    runup: Optional[float] = Field(None, description="Max favorable move")
    drawdown: Optional[float] = Field(None, description="Max adverse move")
    cumulative_pnl: Optional[float] = Field(None, description="Cumulative P&L")
    signal: Optional[str] = Field(None, description="Strategy name")
    exit_reason: Optional[ExitReason] = Field(None, description="Exit reason")

    @field_validator('ts_entry', 'ts_exit')
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Ensure timestamps are timezone-aware UTC"""
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware (UTC)")
        return v

    @field_validator('ts_exit')
    @classmethod
    def validate_exit_after_entry(cls, v: datetime, info) -> datetime:
        """Ensure exit is after entry"""
        if 'ts_entry' in info.data and v < info.data['ts_entry']:
            raise ValueError("Exit timestamp must be after entry timestamp")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "ts_entry": "2025-11-15T12:00:00+00:00",
                "ts_exit": "2025-11-15T14:30:00+00:00",
                "side": "long",
                "entry_price": 43250.50,
                "exit_price": 43500.00,
                "size": 0.02,
                "net_pnl": 4.50,
                "runup": 300.00,
                "drawdown": -50.00,
                "cumulative_pnl": 4.50,
                "signal": "scalper",
                "exit_reason": "take_profit"
            }
        }


class BacktestFile(BaseModel):
    """
    Complete per-pair backtest export file.

    This is the root schema for JSON files stored at:
    data/backtests/{symbol_normalized}.json

    Examples:
      - data/backtests/BTC-USD.json
      - data/backtests/ETH-USD.json

    Attributes:
        symbol: Trading pair in exchange format (e.g., "ETH/USD")
        symbol_id: Normalized symbol ID (e.g., "ETH-USD")
        timeframe: Candle timeframe (e.g., "1m", "1h")
        start_ts: Backtest start timestamp (UTC)
        end_ts: Backtest end timestamp (UTC)
        equity_curve: List of equity points (for PnL chart)
        trades: List of completed trades (for markers + table)
        initial_capital: Starting capital
        final_equity: Ending equity
        total_return_pct: Total return percentage
        sharpe_ratio: Sharpe ratio
        max_drawdown_pct: Maximum drawdown percentage
        win_rate_pct: Win rate percentage
        total_trades: Total number of trades
        profit_factor: Profit factor (gross profit / gross loss)
    """
    symbol: str = Field(..., description="Trading pair (e.g., 'ETH/USD')")
    symbol_id: str = Field(..., description="Normalized symbol (e.g., 'ETH-USD')")
    timeframe: str = Field(..., description="Timeframe (e.g., '1m', '1h')")
    start_ts: datetime = Field(..., description="Backtest start (UTC)")
    end_ts: datetime = Field(..., description="Backtest end (UTC)")
    equity_curve: List[EquityPoint] = Field(..., description="Equity curve points")
    trades: List[Trade] = Field(..., description="Completed trades")

    # Summary metrics
    initial_capital: float = Field(..., gt=0, description="Initial capital")
    final_equity: float = Field(..., gt=0, description="Final equity")
    total_return_pct: float = Field(..., description="Total return %")
    sharpe_ratio: float = Field(..., description="Sharpe ratio")
    max_drawdown_pct: float = Field(..., le=0, description="Max drawdown %")
    win_rate_pct: float = Field(..., ge=0, le=100, description="Win rate %")
    total_trades: int = Field(..., ge=0, description="Total trades")
    profit_factor: float = Field(..., ge=0, description="Profit factor")

    @field_validator('start_ts', 'end_ts')
    @classmethod
    def validate_utc_timestamp(cls, v: datetime) -> datetime:
        """Ensure timestamps are timezone-aware UTC"""
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware (UTC)")
        return v

    @field_validator('end_ts')
    @classmethod
    def validate_end_after_start(cls, v: datetime, info) -> datetime:
        """Ensure end is after start"""
        if 'start_ts' in info.data and v < info.data['start_ts']:
            raise ValueError("End timestamp must be after start timestamp")
        return v

    @field_validator('symbol_id')
    @classmethod
    def validate_symbol_id_format(cls, v: str) -> str:
        """Ensure symbol_id uses dash separator (not slash)"""
        if '/' in v:
            raise ValueError("symbol_id must use dash separator (e.g., 'BTC-USD' not 'BTC/USD')")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTC/USD",
                "symbol_id": "BTC-USD",
                "timeframe": "1h",
                "start_ts": "2025-01-01T00:00:00+00:00",
                "end_ts": "2025-11-15T23:59:59+00:00",
                "equity_curve": [
                    {
                        "ts": "2025-01-01T00:00:00+00:00",
                        "equity": 10000.0,
                        "balance": 10000.0,
                        "unrealized_pnl": 0.0
                    },
                    {
                        "ts": "2025-01-01T01:00:00+00:00",
                        "equity": 10050.0,
                        "balance": 9500.0,
                        "unrealized_pnl": 550.0
                    }
                ],
                "trades": [
                    {
                        "id": 1,
                        "ts_entry": "2025-01-01T12:00:00+00:00",
                        "ts_exit": "2025-01-01T14:30:00+00:00",
                        "side": "long",
                        "entry_price": 43250.50,
                        "exit_price": 43500.00,
                        "size": 0.02,
                        "net_pnl": 4.50,
                        "signal": "scalper",
                        "exit_reason": "take_profit"
                    }
                ],
                "initial_capital": 10000.0,
                "final_equity": 10500.0,
                "total_return_pct": 5.0,
                "sharpe_ratio": 1.8,
                "max_drawdown_pct": -2.5,
                "win_rate_pct": 55.0,
                "total_trades": 100,
                "profit_factor": 1.6
            }
        }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def normalize_symbol(symbol: str) -> str:
    """
    Convert exchange symbol to normalized ID.

    Examples:
        "BTC/USD" -> "BTC-USD"
        "ETH/USD" -> "ETH-USD"
        "SOL/USD" -> "SOL-USD"

    Args:
        symbol: Exchange symbol (e.g., "BTC/USD")

    Returns:
        Normalized symbol ID (e.g., "BTC-USD")
    """
    return symbol.replace("/", "-")


def get_backtest_file_path(symbol: str, base_dir: str = "data/backtests") -> str:
    """
    Get standardized file path for per-pair backtest export.

    Args:
        symbol: Trading pair (e.g., "ETH/USD")
        base_dir: Base directory (default: "data/backtests")

    Returns:
        File path (e.g., "data/backtests/ETH-USD.json")
    """
    symbol_id = normalize_symbol(symbol)
    return f"{base_dir}/{symbol_id}.json"


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "TradeSide",
    "ExitReason",
    "EquityPoint",
    "Trade",
    "BacktestFile",
    "normalize_symbol",
    "get_backtest_file_path",
]
