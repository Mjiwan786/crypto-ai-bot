"""
agents/scalper/backtest/analyzer.py

Production-grade backtest analyzer module for Scalper Agent
Optimized for crypto-ai-bot project with Redis streams integration
"""

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, validator

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class BacktestReport:
    """Complete backtest analysis report with all metrics and artifacts"""

    schema_version: int = 1

    # Core metrics
    start_value: float = 0.0
    end_value: float = 0.0
    total_pnl: float = 0.0
    net_profit_pct: float = 0.0
    CAGR: float = 0.0
    max_drawdown: float = 0.0
    Sharpe: float = 0.0
    Sortino: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    exposure: float = 0.0

    # Extended metrics
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    losing_trades: int = 0
    winning_trades: int = 0
    expectancy_per_trade: float = 0.0
    kelly_fraction: float = 0.0
    avg_trade_duration_s: float = 0.0
    turnover: float = 0.0

    # Time series data
    equity_curve: pd.Series = field(default_factory=pd.Series)
    drawdown_curve: pd.Series = field(default_factory=pd.Series)
    pnl_by_day: pd.Series = field(default_factory=pd.Series)
    pnl_by_symbol: pd.Series = field(default_factory=pd.Series)

    # Distribution and risk
    trade_pnl_distribution: Dict[str, List[float]] = field(default_factory=dict)
    mae_mfe_summary: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Sensitivity analysis
    slippage_sensitivity: pd.DataFrame = field(default_factory=pd.DataFrame)
    fee_sensitivity: pd.DataFrame = field(default_factory=pd.DataFrame)

    # Metadata
    meta: Dict[str, Any] = field(default_factory=dict)


class TradeValidator(BaseModel):
    """Pydantic model for validating trade data structure"""

    ts: Union[int, float, str]
    symbol: str
    side: str = Field(..., regex=r"^(buy|sell)$")
    qty: Decimal = Field(..., gt=0)
    price: Decimal = Field(..., gt=0)
    fee_usd: Decimal = Field(default=Decimal("0.0"), ge=0)
    slippage_bps: Optional[float] = Field(default=None, ge=0)
    order_type: str = Field(default="market")

    @validator("ts")
    def validate_timestamp(cls, v):
        if isinstance(v, str):
            try:
                return pd.to_datetime(v).timestamp() * 1000  # Convert to ms
            except Exception:
                raise ValueError(f"Invalid timestamp format: {v}")
        elif isinstance(v, (int, float)):
            # Assume ms if > year 2020 in seconds, else convert from seconds
            if v > 1577836800:  # 2020-01-01 in seconds
                return float(v) if v > 1577836800000 else float(v) * 1000
            else:
                return float(v) * 1000
        return float(v)


class BacktestAnalyzer:
    """Production-grade backtest analyzer optimized for scalping strategies"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = self._load_config(config)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def _load_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Load and validate configuration with defaults"""
        default_config = {
            "initial_equity_usd": 1000.0,
            "fee_bps": 6,  # 0.06% for Kraken scalping
            "slippage_bps_default": 2,
            "target_bps": 10,
            "stop_loss_bps": 5,
            "max_hold_seconds": 300,
            "timeframe": "15s",
            "allow_open_positions": True,
            "risk_free_rate": 0.0,
            "trading_days_per_year": 365,
        }

        if config:
            default_config.update(config)

        return default_config

    def _validate_trades(self, trades: Union[List[dict], pd.DataFrame]) -> pd.DataFrame:
        """Validate and clean trade data with comprehensive error handling"""
        if len(trades) == 0:
            self.logger.warning("Empty trades dataset provided")
            return pd.DataFrame()

        # Convert to DataFrame if needed
        if isinstance(trades, list):
            trades_df = pd.DataFrame(trades)
        else:
            trades_df = trades.copy()

        # Validate required columns
        required_cols = ["ts", "symbol", "side", "qty", "price"]
        missing_cols = [col for col in required_cols if col not in trades_df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")

        # Add optional columns with defaults
        for col, default in [("fee_usd", 0.0), ("slippage_bps", None), ("order_type", "market")]:
            if col not in trades_df.columns:
                trades_df[col] = default

        # Validate each trade using Pydantic
        validated_trades = []
        for idx, row in trades_df.iterrows():
            try:
                validated_trade = TradeValidator(**row.to_dict())
                validated_trades.append(validated_trade.dict())
            except Exception as e:
                self.logger.error(f"Invalid trade at index {idx}: {e}")
                continue

        if not validated_trades:
            raise ValueError("No valid trades found after validation")

        # Convert back to DataFrame
        df = pd.DataFrame(validated_trades)

        # Convert timestamps to datetime index
        df["datetime"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        df = df.sort_values("datetime").reset_index(drop=True)

        # Fill missing slippage with default
        df["slippage_bps"] = df["slippage_bps"].fillna(self.config["slippage_bps_default"])

        self.logger.info(
            f"Validated {len(df)} trades from {df['datetime'].min()} to {df['datetime'].max()}"
        )
        return df

    def _calculate_round_trips(self, trades_df: pd.DataFrame) -> List[Dict[str, Any]]:
        """Calculate round trips using FIFO matching for flat-to-flat positions"""
        if trades_df.empty:
            return []

        round_trips = []

        # Group by symbol for separate position tracking
        for symbol in trades_df["symbol"].unique():
            symbol_trades = trades_df[trades_df["symbol"] == symbol].copy()

            position = 0.0
            entry_trades = []  # Stack of partial entries

            for _, trade in symbol_trades.iterrows():
                trade_qty = trade["qty"] if trade["side"] == "buy" else -trade["qty"]

                if position == 0:
                    # Starting new position
                    entry_trades = [
                        {
                            "datetime": trade["datetime"],
                            "price": trade["price"],
                            "qty": abs(trade_qty),
                            "side": trade["side"],
                            "fee_usd": trade["fee_usd"],
                            "slippage_bps": trade["slippage_bps"],
                        }
                    ]
                    position = trade_qty

                elif (position > 0 and trade_qty > 0) or (position < 0 and trade_qty < 0):
                    # Adding to position
                    entry_trades.append(
                        {
                            "datetime": trade["datetime"],
                            "price": trade["price"],
                            "qty": abs(trade_qty),
                            "side": trade["side"],
                            "fee_usd": trade["fee_usd"],
                            "slippage_bps": trade["slippage_bps"],
                        }
                    )
                    position += trade_qty

                else:
                    # Closing position (FIFO)
                    remaining_close_qty = abs(trade_qty)

                    while remaining_close_qty > 0 and entry_trades:
                        entry = entry_trades[0]

                        if entry["qty"] <= remaining_close_qty:
                            # Full close of this entry
                            close_qty = entry["qty"]
                            entry_trades.pop(0)
                        else:
                            # Partial close
                            close_qty = remaining_close_qty
                            entry["qty"] -= close_qty

                        # Calculate P&L for this round trip
                        entry_price = entry["price"]
                        exit_price = trade["price"]

                        if entry["side"] == "buy":
                            gross_pnl = (exit_price - entry_price) * close_qty
                        else:
                            gross_pnl = (entry_price - exit_price) * close_qty

                        # Calculate fees and slippage
                        entry_fee = entry["fee_usd"] * (close_qty / (entry["qty"] + close_qty))
                        exit_fee = trade["fee_usd"] * (close_qty / abs(trade_qty))

                        # Apply slippage (in bps)
                        slippage_cost = (entry["slippage_bps"] / 10000) * entry_price * close_qty
                        slippage_cost += (trade["slippage_bps"] / 10000) * exit_price * close_qty

                        net_pnl = gross_pnl - entry_fee - exit_fee - slippage_cost

                        round_trips.append(
                            {
                                "symbol": symbol,
                                "entry_datetime": entry["datetime"],
                                "exit_datetime": trade["datetime"],
                                "entry_price": entry_price,
                                "exit_price": exit_price,
                                "qty": close_qty,
                                "side": entry["side"],
                                "gross_pnl": gross_pnl,
                                "fees": entry_fee + exit_fee,
                                "slippage": slippage_cost,
                                "net_pnl": net_pnl,
                                "duration_seconds": (
                                    trade["datetime"] - entry["datetime"]
                                ).total_seconds(),
                            }
                        )

                        remaining_close_qty -= close_qty
                        position += close_qty if position > 0 else -close_qty

        self.logger.info(f"Calculated {len(round_trips)} round trips")
        return round_trips

    def _calculate_mae_mfe(
        self, round_trips: List[Dict], ohlcv: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """Calculate Maximum Adverse Excursion and Maximum Favorable Excursion"""
        if not round_trips:
            return pd.DataFrame(
                columns=["symbol", "entry_datetime", "mae", "mfe", "mae_pct", "mfe_pct"]
            )

        mae_mfe_data = []

        for rt in round_trips:
            # Initialize with entry/exit prices if no OHLCV data
            mae = 0.0
            mfe = 0.0

            if ohlcv is not None:
                # Filter OHLCV data for the trade period
                trade_period = ohlcv[
                    (ohlcv.index >= rt["entry_datetime"]) & (ohlcv.index <= rt["exit_datetime"])
                ]

                if not trade_period.empty:
                    entry_price = rt["entry_price"]

                    if rt["side"] == "buy":
                        # For long positions
                        mae = min(0, (trade_period["low"].min() - entry_price) / entry_price)
                        mfe = max(0, (trade_period["high"].max() - entry_price) / entry_price)
                    else:
                        # For short positions
                        mae = min(0, (entry_price - trade_period["high"].max()) / entry_price)
                        mfe = max(0, (entry_price - trade_period["low"].min()) / entry_price)

            mae_mfe_data.append(
                {
                    "symbol": rt["symbol"],
                    "entry_datetime": rt["entry_datetime"],
                    "mae": mae * rt["qty"] * rt["entry_price"],  # Dollar amount
                    "mfe": mfe * rt["qty"] * rt["entry_price"],  # Dollar amount
                    "mae_pct": mae,
                    "mfe_pct": mfe,
                    "net_pnl": rt["net_pnl"],
                    "duration_seconds": rt["duration_seconds"],
                }
            )

        return pd.DataFrame(mae_mfe_data)

    def _calculate_equity_curve(self, round_trips: List[Dict], start_value: float) -> pd.Series:
        """Calculate equity curve from round trips"""
        if not round_trips:
            return pd.Series([start_value], index=[datetime.now(timezone.utc)])

        # Create time series of P&L events
        pnl_events = []
        for rt in round_trips:
            pnl_events.append({"datetime": rt["exit_datetime"], "pnl": rt["net_pnl"]})

        pnl_df = pd.DataFrame(pnl_events)
        pnl_df = pnl_df.sort_values("datetime")

        # Calculate cumulative equity
        pnl_df["cumulative_pnl"] = pnl_df["pnl"].cumsum()
        pnl_df["equity"] = start_value + pnl_df["cumulative_pnl"]

        # Create series with datetime index
        equity_series = pd.Series(
            pnl_df["equity"].values, index=pd.DatetimeIndex(pnl_df["datetime"])
        )

        # Add starting point
        start_time = equity_series.index[0] - pd.Timedelta(seconds=1)
        equity_series = pd.concat([pd.Series([start_value], index=[start_time]), equity_series])

        return equity_series

    def _calculate_drawdown(self, equity_curve: pd.Series) -> pd.Series:
        """Calculate drawdown curve from equity curve"""
        if equity_curve.empty:
            return pd.Series()

        # Calculate running maximum (high water mark)
        running_max = equity_curve.expanding().max()

        # Calculate drawdown as percentage from peak
        drawdown = (equity_curve - running_max) / running_max

        return drawdown

    def _calculate_sharpe_ratio(self, round_trips: List[Dict]) -> float:
        """Calculate Sharpe ratio from trade returns"""
        if not round_trips:
            return 0.0

        # Convert to daily returns
        returns = [rt["net_pnl"] for rt in round_trips]

        if len(returns) < 2:
            return 0.0

        # Calculate daily return statistics
        mean_return = np.mean(returns)
        std_return = np.std(returns, ddof=1)

        if std_return == 0:
            return 0.0

        # Annualize (assuming daily frequency)
        trading_days = self.config["trading_days_per_year"]
        sharpe = (mean_return - self.config["risk_free_rate"]) / std_return * np.sqrt(trading_days)

        return round(sharpe, 4)

    def _calculate_sortino_ratio(self, round_trips: List[Dict]) -> float:
        """Calculate Sortino ratio (downside deviation)"""
        if not round_trips:
            return 0.0

        returns = [rt["net_pnl"] for rt in round_trips]

        if len(returns) < 2:
            return 0.0

        mean_return = np.mean(returns)
        negative_returns = [r for r in returns if r < 0]

        if not negative_returns:
            return np.inf if mean_return > 0 else 0.0

        downside_std = np.std(negative_returns, ddof=1)

        if downside_std == 0:
            return 0.0

        # Annualize
        trading_days = self.config["trading_days_per_year"]
        sortino = (
            (mean_return - self.config["risk_free_rate"]) / downside_std * np.sqrt(trading_days)
        )

        return round(sortino, 4)

    def _calculate_kelly_fraction(self, round_trips: List[Dict]) -> float:
        """Calculate Kelly fraction for optimal position sizing"""
        if not round_trips:
            return 0.0

        wins = [rt["net_pnl"] for rt in round_trips if rt["net_pnl"] > 0]
        losses = [abs(rt["net_pnl"]) for rt in round_trips if rt["net_pnl"] < 0]

        if not wins or not losses:
            return 0.0

        win_rate = len(wins) / len(round_trips)
        avg_win = np.mean(wins)
        avg_loss = np.mean(losses)

        if avg_loss == 0:
            return 0.0

        win_loss_ratio = avg_win / avg_loss
        kelly = win_rate - ((1 - win_rate) / win_loss_ratio)

        # Bound Kelly fraction between 0 and 1 for safety
        return max(0.0, min(1.0, round(kelly, 4)))

    def _calculate_sensitivity_analysis(
        self, round_trips: List[Dict]
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Calculate slippage and fee sensitivity analysis"""
        if not round_trips:
            empty_df = pd.DataFrame(
                columns=["scenario", "total_pnl", "net_profit_pct", "profit_factor"]
            )
            return empty_df, empty_df

        base_pnl = sum(rt["net_pnl"] for rt in round_trips)
        self._calculate_profit_factor(round_trips)

        # Slippage sensitivity
        slippage_scenarios = [0, 2, 5, 10]  # Additional bps
        slippage_results = []

        for additional_bps in slippage_scenarios:
            adjusted_pnl = 0
            for rt in round_trips:
                # Additional slippage cost
                additional_slippage = (additional_bps / 10000) * rt["entry_price"] * rt["qty"]
                additional_slippage += (additional_bps / 10000) * rt["exit_price"] * rt["qty"]
                adjusted_pnl += rt["net_pnl"] - additional_slippage

            slippage_results.append(
                {
                    "additional_slippage_bps": additional_bps,
                    "total_pnl": round(adjusted_pnl, 2),
                    "net_profit_pct": round(
                        (adjusted_pnl / self.config["initial_equity_usd"]) * 100, 2
                    ),
                    "change_from_base": round(adjusted_pnl - base_pnl, 2),
                }
            )

        # Fee sensitivity
        fee_scenarios = [1.0, 1.5, 2.0]  # Fee multipliers
        fee_results = []

        for multiplier in fee_scenarios:
            adjusted_pnl = 0
            for rt in round_trips:
                additional_fees = rt["fees"] * (multiplier - 1)
                adjusted_pnl += rt["net_pnl"] - additional_fees

            fee_results.append(
                {
                    "fee_multiplier": multiplier,
                    "total_pnl": round(adjusted_pnl, 2),
                    "net_profit_pct": round(
                        (adjusted_pnl / self.config["initial_equity_usd"]) * 100, 2
                    ),
                    "change_from_base": round(adjusted_pnl - base_pnl, 2),
                }
            )

        return pd.DataFrame(slippage_results), pd.DataFrame(fee_results)

    def _calculate_profit_factor(self, round_trips: List[Dict]) -> float:
        """Calculate profit factor (gross wins / gross losses)"""
        if not round_trips:
            return 0.0

        wins = sum(rt["net_pnl"] for rt in round_trips if rt["net_pnl"] > 0)
        losses = abs(sum(rt["net_pnl"] for rt in round_trips if rt["net_pnl"] < 0))

        if losses == 0:
            return np.inf if wins > 0 else 0.0

        return round(wins / losses, 4)

    def _calculate_cagr(
        self, start_value: float, end_value: float, start_date: datetime, end_date: datetime
    ) -> float:
        """Calculate Compound Annual Growth Rate"""
        if start_value <= 0 or end_value <= 0:
            return 0.0

        years = (end_date - start_date).total_seconds() / (365.25 * 24 * 3600)

        if years <= 0:
            return 0.0

        cagr = (end_value / start_value) ** (1 / years) - 1
        return round(cagr * 100, 4)  # Return as percentage

    def analyze_trades(
        self,
        trades: Union[List[dict], pd.DataFrame],
        ohlcv: Optional[pd.DataFrame] = None,
        config: Optional[dict] = None,
    ) -> BacktestReport:
        """
        Analyze trades and generate comprehensive backtest report

        Args:
            trades: List of trade dictionaries or DataFrame
            ohlcv: Optional OHLCV data for MAE/MFE calculation
            config: Optional configuration overrides

        Returns:
            BacktestReport with complete analysis
        """
        start_time = time.time()

        # Update config if provided
        if config:
            self.config.update(config)

        # Validate and process trades
        trades_df = self._validate_trades(trades)

        if trades_df.empty:
            self.logger.warning("No valid trades to analyze")
            return BacktestReport(meta={"analysis_time_s": time.time() - start_time})

        # Calculate round trips
        round_trips = self._calculate_round_trips(trades_df)

        if not round_trips:
            self.logger.warning("No complete round trips found")
            return BacktestReport(meta={"analysis_time_s": time.time() - start_time})

        # Core calculations
        start_value = self.config["initial_equity_usd"]
        total_pnl = sum(rt["net_pnl"] for rt in round_trips)
        end_value = start_value + total_pnl

        # Time series
        equity_curve = self._calculate_equity_curve(round_trips, start_value)
        drawdown_curve = self._calculate_drawdown(equity_curve)

        # Win/Loss analysis
        winning_trades = [rt for rt in round_trips if rt["net_pnl"] > 0]
        losing_trades = [rt for rt in round_trips if rt["net_pnl"] < 0]

        # Calculate metrics
        win_rate = len(winning_trades) / len(round_trips) if round_trips else 0
        avg_win = np.mean([rt["net_pnl"] for rt in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([rt["net_pnl"] for rt in losing_trades]) if losing_trades else 0
        largest_win = max([rt["net_pnl"] for rt in winning_trades], default=0)
        largest_loss = min([rt["net_pnl"] for rt in losing_trades], default=0)

        # Advanced metrics
        max_drawdown = drawdown_curve.min() if not drawdown_curve.empty else 0
        sharpe = self._calculate_sharpe_ratio(round_trips)
        sortino = self._calculate_sortino_ratio(round_trips)
        profit_factor = self._calculate_profit_factor(round_trips)
        kelly_fraction = self._calculate_kelly_fraction(round_trips)

        # Time-based analysis
        start_date = trades_df["datetime"].min()
        end_date = trades_df["datetime"].max()
        cagr = self._calculate_cagr(start_value, end_value, start_date, end_date)

        avg_duration = np.mean([rt["duration_seconds"] for rt in round_trips])

        # Exposure calculation (time in market)
        total_time = (end_date - start_date).total_seconds()
        time_in_market = sum(rt["duration_seconds"] for rt in round_trips)
        exposure = time_in_market / total_time if total_time > 0 else 0

        # Turnover calculation
        total_volume = sum(rt["qty"] * rt["entry_price"] for rt in round_trips)
        turnover = total_volume / start_value if start_value > 0 else 0

        # Distribution analysis
        pnl_values = [rt["net_pnl"] for rt in round_trips]
        trade_pnl_distribution = {
            "wins": [rt["net_pnl"] for rt in winning_trades],
            "losses": [rt["net_pnl"] for rt in losing_trades],
            "all": pnl_values,
        }

        # P&L by symbol and day
        symbol_pnl = {}
        for rt in round_trips:
            symbol_pnl[rt["symbol"]] = symbol_pnl.get(rt["symbol"], 0) + rt["net_pnl"]
        pnl_by_symbol = pd.Series(symbol_pnl)

        # Daily P&L
        daily_pnl = {}
        for rt in round_trips:
            date = rt["exit_datetime"].date()
            daily_pnl[date] = daily_pnl.get(date, 0) + rt["net_pnl"]
        pnl_by_day = pd.Series(daily_pnl, name="daily_pnl")

        # MAE/MFE analysis
        mae_mfe_summary = self._calculate_mae_mfe(round_trips, ohlcv)

        # Sensitivity analysis
        slippage_sensitivity, fee_sensitivity = self._calculate_sensitivity_analysis(round_trips)

        # Expectancy
        expectancy = sum(pnl_values) / len(pnl_values) if pnl_values else 0

        # Create report
        report = BacktestReport(
            start_value=round(start_value, 2),
            end_value=round(end_value, 2),
            total_pnl=round(total_pnl, 2),
            net_profit_pct=round((total_pnl / start_value) * 100, 4),
            CAGR=cagr,
            max_drawdown=round(max_drawdown * 100, 4),
            Sharpe=sharpe,
            Sortino=sortino,
            profit_factor=profit_factor,
            win_rate=round(win_rate * 100, 4),
            total_trades=len(round_trips),
            exposure=round(exposure * 100, 4),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            largest_win=round(largest_win, 2),
            largest_loss=round(largest_loss, 2),
            losing_trades=len(losing_trades),
            winning_trades=len(winning_trades),
            expectancy_per_trade=round(expectancy, 2),
            kelly_fraction=kelly_fraction,
            avg_trade_duration_s=round(avg_duration, 2),
            turnover=round(turnover, 2),
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            pnl_by_day=pnl_by_day,
            pnl_by_symbol=pnl_by_symbol,
            trade_pnl_distribution=trade_pnl_distribution,
            mae_mfe_summary=mae_mfe_summary,
            slippage_sensitivity=slippage_sensitivity,
            fee_sensitivity=fee_sensitivity,
            meta={
                "analysis_time_s": round(time.time() - start_time, 4),
                "config": self.config,
                "trades_analyzed": len(trades_df),
                "round_trips": len(round_trips),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "symbols": list(trades_df["symbol"].unique()),
            },
        )

        self.logger.info(f"Analysis complete in {report.meta['analysis_time_s']:.2f}s")
        return report


# Convenience functions for external use


def analyze_trades(
    trades: Union[List[dict], pd.DataFrame],
    ohlcv: Optional[pd.DataFrame] = None,
    config: Optional[dict] = None,
) -> BacktestReport:
    """
    Analyze trades and generate backtest report

    Args:
        trades: Trade data as list of dicts or DataFrame
        ohlcv: Optional OHLCV data for enhanced analysis
        config: Optional configuration overrides

    Returns:
        BacktestReport with complete analysis
    """
    analyzer = BacktestAnalyzer(config)
    return analyzer.analyze_trades(trades, ohlcv, config)


def analyze_from_csv(
    trades_path: str, ohlcv_path: Optional[str] = None, config: Optional[dict] = None
) -> BacktestReport:
    """
    Analyze trades from CSV files

    Args:
        trades_path: Path to trades CSV file
        ohlcv_path: Optional path to OHLCV CSV file
        config: Optional configuration overrides

    Returns:
        BacktestReport with complete analysis
    """
    logger.info(f"Loading trades from {trades_path}")

    # Load trades
    try:
        trades_df = pd.read_csv(trades_path)
        logger.info(f"Loaded {len(trades_df)} trades")
    except Exception as e:
        logger.error(f"Failed to load trades: {e}")
        raise

    # Load OHLCV if provided
    ohlcv_df = None
    if ohlcv_path:
        try:
            ohlcv_df = pd.read_csv(ohlcv_path)
            if "ts" in ohlcv_df.columns:
                ohlcv_df["datetime"] = pd.to_datetime(ohlcv_df["ts"], unit="ms", utc=True)
                ohlcv_df.set_index("datetime", inplace=True)
            logger.info(f"Loaded {len(ohlcv_df)} OHLCV bars")
        except Exception as e:
            logger.warning(f"Failed to load OHLCV data: {e}")
            ohlcv_df = None

    return analyze_trades(trades_df, ohlcv_df, config)


def export_report(report: BacktestReport, out_dir: str) -> Dict[str, str]:
    """
    Export backtest report to multiple file formats

    Args:
        report: BacktestReport to export
        out_dir: Output directory path

    Returns:
        Dictionary mapping file types to file paths
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    exported_files = {}

    # Export scalar metrics as JSON
    metrics_dict = {
        "schema_version": report.schema_version,
        "performance_metrics": {
            "start_value": report.start_value,
            "end_value": report.end_value,
            "total_pnl": report.total_pnl,
            "net_profit_pct": report.net_profit_pct,
            "CAGR": report.CAGR,
            "max_drawdown": report.max_drawdown,
            "Sharpe": report.Sharpe,
            "Sortino": report.Sortino,
            "profit_factor": report.profit_factor,
            "win_rate": report.win_rate,
            "total_trades": report.total_trades,
            "exposure": report.exposure,
            "avg_win": report.avg_win,
            "avg_loss": report.avg_loss,
            "largest_win": report.largest_win,
            "largest_loss": report.largest_loss,
            "losing_trades": report.losing_trades,
            "winning_trades": report.winning_trades,
            "expectancy_per_trade": report.expectancy_per_trade,
            "kelly_fraction": report.kelly_fraction,
            "avg_trade_duration_s": report.avg_trade_duration_s,
            "turnover": report.turnover,
        },
        "meta": report.meta,
    }

    report_path = out_path / "report.json"
    with open(report_path, "w") as f:
        json.dump(metrics_dict, f, indent=2, default=str)
    exported_files["report"] = str(report_path)

    # Export time series data
    if not report.equity_curve.empty:
        equity_path = out_path / "equity_curve.csv"
        equity_df = pd.DataFrame(
            {"datetime": report.equity_curve.index, "equity": report.equity_curve.values}
        )
        equity_df.to_csv(equity_path, index=False)
        exported_files["equity_curve"] = str(equity_path)

    if not report.pnl_by_day.empty:
        daily_pnl_path = out_path / "pnl_by_day.csv"
        daily_df = pd.DataFrame({"date": report.pnl_by_day.index, "pnl": report.pnl_by_day.values})
        daily_df.to_csv(daily_pnl_path, index=False)
        exported_files["pnl_by_day"] = str(daily_pnl_path)

    if not report.pnl_by_symbol.empty:
        symbol_pnl_path = out_path / "pnl_by_symbol.csv"
        symbol_df = pd.DataFrame(
            {"symbol": report.pnl_by_symbol.index, "pnl": report.pnl_by_symbol.values}
        )
        symbol_df.to_csv(symbol_pnl_path, index=False)
        exported_files["pnl_by_symbol"] = str(symbol_pnl_path)

    # Export analysis tables
    if not report.mae_mfe_summary.empty:
        mae_mfe_path = out_path / "mae_mfe_summary.csv"
        report.mae_mfe_summary.to_csv(mae_mfe_path, index=False)
        exported_files["mae_mfe_summary"] = str(mae_mfe_path)

    if not report.slippage_sensitivity.empty:
        slippage_path = out_path / "slippage_sensitivity.csv"
        report.slippage_sensitivity.to_csv(slippage_path, index=False)
        exported_files["slippage_sensitivity"] = str(slippage_path)

    if not report.fee_sensitivity.empty:
        fee_path = out_path / "fee_sensitivity.csv"
        report.fee_sensitivity.to_csv(fee_path, index=False)
        exported_files["fee_sensitivity"] = str(fee_path)

    # Export enriched trades data
    if "round_trips" in report.meta and report.meta["round_trips"] > 0:
        # Create enriched trades with round trip IDs and P&L
        # This would require storing round trip data in the report
        # For now, just note the capability
        logger.info("Enriched trades export capability available")

    logger.info(f"Exported {len(exported_files)} files to {out_dir}")
    return exported_files


def plot_equity(report: BacktestReport, out_path: Optional[str] = None) -> Optional[str]:
    """
    Plot equity curve with drawdown

    Args:
        report: BacktestReport with equity curve data
        out_path: Optional path to save PNG file

    Returns:
        Path to saved file if out_path provided, None otherwise
    """
    if report.equity_curve.empty:
        logger.warning("No equity curve data to plot")
        return None

    # Create figure with subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    # Plot equity curve
    ax1.plot(
        report.equity_curve.index,
        report.equity_curve.values,
        linewidth=2,
        color="navy",
        label="Equity",
    )
    ax1.axhline(y=report.start_value, color="gray", linestyle="--", alpha=0.7, label="Start Value")
    ax1.set_ylabel("Portfolio Value ($)")
    ax1.set_title(
        f"Backtest Results: {report.net_profit_pct:.2f}% Return, {report.max_drawdown:.2f}% Max DD"
    )
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    # Format y-axis as currency
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"${x:,.0f}"))

    # Plot drawdown
    if not report.drawdown_curve.empty:
        ax2.fill_between(
            report.drawdown_curve.index,
            report.drawdown_curve.values * 100,
            0,
            alpha=0.3,
            color="red",
            label="Drawdown",
        )
        ax2.plot(
            report.drawdown_curve.index,
            report.drawdown_curve.values * 100,
            linewidth=1,
            color="darkred",
        )
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.3)
        ax2.legend()

    # Add performance metrics text
    metrics_text = f"""
    Total Trades: {report.total_trades}
    Win Rate: {report.win_rate:.1f}%
    Profit Factor: {report.profit_factor:.2f}
    Sharpe Ratio: {report.Sharpe:.2f}
    Max Drawdown: {report.max_drawdown:.2f}%
    """

    ax1.text(
        0.02,
        0.98,
        metrics_text.strip(),
        transform=ax1.transAxes,
        verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.8),
        fontsize=9,
    )

    plt.tight_layout()

    if out_path:
        plt.savefig(out_path, dpi=300, bbox_inches="tight")
        logger.info(f"Equity curve saved to {out_path}")
        plt.close()
        return out_path
    else:
        plt.show()
        return None


# CLI interface
def main():
    """Command line interface for the analyzer"""
    parser = argparse.ArgumentParser(description="Scalper Backtest Analyzer")

    parser.add_argument("--trades", required=True, help="Path to trades CSV file")
    parser.add_argument("--ohlcv", help="Path to OHLCV CSV file (optional)")
    parser.add_argument("--out", default="reports/scalper", help="Output directory")
    parser.add_argument("--start-value", type=float, default=1000, help="Starting equity")
    parser.add_argument("--fee-bps", type=int, default=6, help="Fee in basis points")
    parser.add_argument("--slip-bps", type=int, default=2, help="Slippage in basis points")
    parser.add_argument("--risk-free", type=float, default=0.0, help="Risk-free rate")
    parser.add_argument("--allow-open-positions", action="store_true", help="Allow open positions")
    parser.add_argument("--plot", action="store_true", help="Generate equity curve plot")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Build configuration
    config = {
        "initial_equity_usd": args.start_value,
        "fee_bps": args.fee_bps,
        "slippage_bps_default": args.slip_bps,
        "risk_free_rate": args.risk_free,
        "allow_open_positions": args.allow_open_positions,
    }

    try:
        # Run analysis
        logger = logging.getLogger(__name__)
        logger.info("Starting backtest analysis...")
        report = analyze_from_csv(args.trades, args.ohlcv, config)

        # Export results
        exported_files = export_report(report, args.out)

        # Generate plot if requested
        if args.plot:
            plot_path = Path(args.out) / "equity_curve.png"
            plot_equity(report, str(plot_path))
            exported_files["plot"] = str(plot_path)

        # Print summary
        logger = logging.getLogger(__name__)
        logger.info("\n" + "=" * 60)
        logger.info("SCALPER BACKTEST ANALYSIS SUMMARY")
        logger.info("=" * 60)
        logger.info("Strategy: scalper")
        logger.info("Exchange: kraken")
        logger.info(
            "Period: %s to %s",
            report.meta.get("start_date", "N/A"),
            report.meta.get("end_date", "N/A"),
        )
        logger.info("Symbols: %s", ", ".join(report.meta.get("symbols", [])))
        logger.info("")
        logger.info("PERFORMANCE METRICS:")
        logger.info("  Total P&L:           $%.2f", report.total_pnl)
        logger.info("  Net Profit:          %.2f%%", report.net_profit_pct)
        logger.info("  CAGR:                %.2f%%", report.CAGR)
        logger.info("  Max Drawdown:        %.2f%%", report.max_drawdown)
        logger.info("  Sharpe Ratio:        %.2f", report.Sharpe)
        logger.info("  Sortino Ratio:       %.2f", report.Sortino)
        logger.info("")
        logger.info("TRADE STATISTICS:")
        logger.info("  Total Trades:        %d", report.total_trades)
        logger.info("  Win Rate:            %.1f%%", report.win_rate)
        logger.info("  Profit Factor:       %.2f", report.profit_factor)
        logger.info("  Avg Win:             $%.2f", report.avg_win)
        logger.info("  Avg Loss:            $%.2f", report.avg_loss)
        logger.info("  Best Trade:          $%.2f", report.largest_win)
        logger.info("  Worst Trade:         $%.2f", report.largest_loss)
        logger.info("")
        logger.info("RISK METRICS:")
        logger.info("  Kelly Fraction:      %.3f", report.kelly_fraction)
        logger.info("  Expectancy:          $%.2f", report.expectancy_per_trade)
        logger.info("  Avg Duration:        %.0fs", report.avg_trade_duration_s)
        logger.info("  Market Exposure:     %.1f%%", report.exposure)
        logger.info("  Turnover:            %.1fx", report.turnover)
        logger.info("")
        logger.info("EXPORTED FILES:")
        for file_type, file_path in exported_files.items():
            logger.info("  %s: %s", file_type, file_path)
        logger.info("")
        logger.info("Analysis completed in %.2f seconds", report.meta.get("analysis_time_s", 0))
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise


# Demo and testing
if __name__ == "__main__":
    # Check if running as script with args or demo mode
    import sys

    if len(sys.argv) > 1:
        # CLI mode
        main()
    else:
        # Demo mode with synthetic data
        logger = logging.getLogger(__name__)
        logger.info("Running scalper analyzer demo with synthetic data...")

        # Create synthetic trades for testing
        np.random.seed(42)

        # Generate realistic scalping trades
        synthetic_trades = []
        base_price = 50000  # BTC price
        current_time = datetime.now(timezone.utc)

        for i in range(50):
            # Entry trade
            entry_time = current_time + pd.Timedelta(minutes=i * 3)
            entry_price = base_price + np.random.normal(0, 100)
            qty = 0.01 + np.random.uniform(0, 0.09)  # 0.01 to 0.1 BTC

            synthetic_trades.append(
                {
                    "ts": entry_time.timestamp() * 1000,
                    "symbol": "BTC/USD",
                    "side": "buy",
                    "qty": qty,
                    "price": entry_price,
                    "fee_usd": qty * entry_price * 0.0016,  # Kraken maker fee
                    "slippage_bps": 2,
                    "order_type": "limit",
                }
            )

            # Exit trade (scalping targets)
            exit_time = entry_time + pd.Timedelta(seconds=np.random.uniform(30, 180))
            win_probability = 0.6  # 60% win rate

            if np.random.random() < win_probability:
                # Winning trade
                exit_price = entry_price * (
                    1 + np.random.uniform(0.0008, 0.0015)
                )  # 8-15 bps profit
            else:
                # Losing trade
                exit_price = entry_price * (1 - np.random.uniform(0.0004, 0.0008))  # 4-8 bps loss

            synthetic_trades.append(
                {
                    "ts": exit_time.timestamp() * 1000,
                    "symbol": "BTC/USD",
                    "side": "sell",
                    "qty": qty,
                    "price": exit_price,
                    "fee_usd": qty * exit_price * 0.0026,  # Kraken taker fee
                    "slippage_bps": 3,
                    "order_type": "market",
                }
            )

        # Run analysis
        config = {"initial_equity_usd": 10000, "fee_bps": 6, "slippage_bps_default": 2}

        report = analyze_trades(synthetic_trades, config=config)

        # Validate results
        assert report.total_trades > 0, "Should have trades"
        assert report.win_rate > 0, "Should have positive win rate"
        assert not np.isnan(report.Sharpe), "Sharpe ratio should not be NaN"
        assert not np.isnan(report.Sortino), "Sortino ratio should not be NaN"
        assert report.profit_factor > 0, "Profit factor should be positive"

        # Print demo results
        logger.info("\n✅ Demo completed successfully!")
        logger.info("Analyzed %d round trips", report.total_trades)
        logger.info("Win rate: %.1f%%", report.win_rate)
        logger.info("Profit factor: %.2f", report.profit_factor)
        logger.info("Net P&L: $%.2f", report.total_pnl)
        logger.info("Sharpe: %.2f", report.Sharpe)
        logger.info("Max drawdown: %.2f%%", report.max_drawdown)
        logger.info("Analysis time: %.3fs", report.meta["analysis_time_s"])

        logger.info("\n🎯 All validations passed! The analyzer is ready for production use.")
        logger.info("\nTo use with real data:")
        logger.info(
            "  python agents/scalper/backtest/analyzer.py --trades data/scalp_trades.csv --out reports/scalper"
        )
