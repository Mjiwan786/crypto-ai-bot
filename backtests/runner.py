"""
backtests/runner.py - Deterministic Backtest Runner

Production-grade backtesting engine that replays historical OHLCV data through
the same detector/router/strategies/risk code used in live trading.

Features:
- Deterministic execution with fixed random seed
- Historical OHLCV replay
- Same strategies and risk management as live
- Comprehensive metrics (monthly ROI, PF, Sharpe, DD)
- Equity curve CSV export
- JSON report generation
- Fail-fast on DD > 20%

Architecture:
1. Load historical OHLCV data for pairs/timeframes
2. Replay bar-by-bar through engine:
   - Detect regime
   - Route to strategy
   - Size position via risk manager
   - Execute simulated trade
3. Track equity curve and closed trades
4. Calculate comprehensive metrics
5. Generate reports

Per PRD §12:
- 2-3 year data across regimes
- Report monthly ROI, PF, DD, Sharpe
- Fail fast if DD > 20%

Author: Crypto AI Bot Team
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ai_engine.regime_detector.detector import RegimeDetector, RegimeConfig
from ai_engine.schemas import RegimeLabel
from ai_engine.events import MarketSnapshotEvent as MarketSnapshot
from agents.risk_manager import RiskConfig, RiskManager, SignalInput
from agents.strategy_router import RouterConfig, StrategyRouter
from backtests.metrics import (
    BacktestMetrics,
    EquityPoint,
    MetricsCalculator,
    Trade,
)
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum_strategy import MomentumStrategy
from ml import EnsemblePredictor, MLConfig

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class BacktestConfig:
    """
    Backtest configuration.

    Attributes:
        # Capital
        initial_capital: Starting capital
        # Costs
        fee_bps: Trading fee in basis points (e.g., 5 = 0.05%)
        slippage_bps: Slippage in basis points (e.g., 2 = 0.02%)
        # Risk
        max_drawdown_threshold: Max DD before failing fast (default: 20%)
        # Randomness
        random_seed: Random seed for determinism (default: 42)
        # Strategies
        regime_config: Regime detector config
        router_config: Strategy router config
        risk_config: Risk manager config
    """
    # Capital
    initial_capital: Decimal = Decimal("10000.00")

    # Costs
    fee_bps: Decimal = Decimal("5.0")  # 0.05%
    slippage_bps: Decimal = Decimal("2.0")  # 0.02%

    # Risk
    max_drawdown_threshold: Decimal = Decimal("20.0")  # 20%

    # Randomness
    random_seed: int = 42

    # Component configs
    regime_config: Optional[RegimeConfig] = None
    router_config: Optional[RouterConfig] = None
    risk_config: Optional[RiskConfig] = None
    ml_config: Optional[MLConfig] = None

    # ML toggle
    use_ml_filter: bool = False

    def __post_init__(self):
        """Initialize default component configs if not provided"""
        if self.regime_config is None:
            self.regime_config = RegimeConfig()

        if self.router_config is None:
            self.router_config = RouterConfig()

        if self.risk_config is None:
            self.risk_config = RiskConfig()

        if self.ml_config is None:
            self.ml_config = MLConfig(enabled=self.use_ml_filter)


# =============================================================================
# POSITION TRACKING
# =============================================================================

@dataclass
class OpenPosition:
    """
    Tracks an open position.

    Attributes:
        pair: Trading pair
        side: Trade direction (long/short)
        entry_time: Entry timestamp
        entry_price: Entry price
        size: Position size
        stop_loss: Stop loss price
        take_profit: Take profit price
        strategy: Strategy name
    """
    pair: str
    side: str
    entry_time: datetime
    entry_price: Decimal
    size: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    strategy: str


# =============================================================================
# BACKTEST RESULT
# =============================================================================

@dataclass
class BacktestResult:
    """
    Complete backtest result.

    Attributes:
        metrics: Calculated metrics
        trades: List of closed trades
        equity_curve: Equity curve points
        config: Backtest configuration
        pairs: Trading pairs
        timeframe: Timeframe
        start_date: Start date
        end_date: End date
    """
    metrics: BacktestMetrics
    trades: List[Trade]
    equity_curve: List[EquityPoint]
    config: BacktestConfig
    pairs: List[str]
    timeframe: str
    start_date: datetime
    end_date: datetime

    def save_report(self, path: Path) -> None:
        """
        Save JSON report to file.

        Args:
            path: Output file path
        """
        report = {
            "summary": {
                "pairs": self.pairs,
                "timeframe": self.timeframe,
                "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(),
                "duration_days": self.metrics.duration_days,
                "initial_capital": float(self.metrics.initial_capital),
                "final_capital": float(self.metrics.final_capital),
                "total_return": float(self.metrics.total_return),
                "total_return_pct": float(self.metrics.total_return_pct),
            },
            "monthly_returns": {
                month: float(ret) for month, ret in self.metrics.monthly_returns.items()
            },
            "monthly_stats": {
                "mean_roi": float(self.metrics.monthly_roi_mean),
                "median_roi": float(self.metrics.monthly_roi_median),
                "std_roi": float(self.metrics.monthly_roi_std),
            },
            "trade_stats": {
                "total_trades": self.metrics.total_trades,
                "winning_trades": self.metrics.winning_trades,
                "losing_trades": self.metrics.losing_trades,
                "win_rate": float(self.metrics.win_rate),
            },
            "profit_metrics": {
                "gross_profit": float(self.metrics.gross_profit),
                "gross_loss": float(self.metrics.gross_loss),
                "profit_factor": float(self.metrics.profit_factor),
                "avg_win": float(self.metrics.avg_win),
                "avg_loss": float(self.metrics.avg_loss),
                "expectancy": float(self.metrics.expectancy),
            },
            "risk_metrics": {
                "max_drawdown": float(self.metrics.max_drawdown),
                "max_drawdown_duration": self.metrics.max_drawdown_duration,
                "sharpe_ratio": float(self.metrics.sharpe_ratio),
                "sortino_ratio": float(self.metrics.sortino_ratio),
                "calmar_ratio": float(self.metrics.calmar_ratio),
            },
            "costs": {
                "total_fees": float(self.metrics.total_fees),
                "fees_pct": float(self.metrics.fees_pct),
            },
            "config": {
                "initial_capital": float(self.config.initial_capital),
                "fee_bps": float(self.config.fee_bps),
                "slippage_bps": float(self.config.slippage_bps),
                "random_seed": self.config.random_seed,
            },
        }

        with open(path, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Report saved to {path}")

    def save_equity_curve(self, path: Path) -> None:
        """
        Save equity curve to CSV file.

        Args:
            path: Output file path
        """
        df = pd.DataFrame([
            {
                "timestamp": point.timestamp.isoformat(),
                "equity": float(point.equity),
                "cash": float(point.cash),
                "position_value": float(point.position_value),
                "pnl": float(point.pnl),
            }
            for point in self.equity_curve
        ])

        df.to_csv(path, index=False)
        logger.info(f"Equity curve saved to {path}")


# =============================================================================
# BACKTEST RUNNER
# =============================================================================

class BacktestRunner:
    """
    Deterministic backtest runner with historical replay.

    Replays historical OHLCV data through the same engine components used
    in live trading (detector, router, strategies, risk manager).

    All execution is deterministic given fixed random seed.
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        """
        Initialize backtest runner.

        Args:
            config: Backtest configuration (uses defaults if None)
        """
        self.config = config or BacktestConfig()

        # Set random seed for determinism
        random.seed(self.config.random_seed)
        np.random.seed(self.config.random_seed)

        # Initialize components
        self.regime_detector = RegimeDetector(config=self.config.regime_config)
        self.router = StrategyRouter(config=self.config.router_config)
        self.risk_manager = RiskManager(config=self.config.risk_config)

        # Initialize ML predictor if enabled
        self.ml_predictor = None
        if self.config.use_ml_filter:
            self.ml_predictor = EnsemblePredictor(config=self.config.ml_config)
            logger.info(f"ML filter enabled: min_confidence={self.config.ml_config.min_alignment_confidence:.2f}")

        # Register strategies
        momentum_strategy = MomentumStrategy()
        mean_reversion_strategy = MeanReversionStrategy()
        self.router.register("momentum", momentum_strategy)
        self.router.register("mean_reversion", mean_reversion_strategy)

        # Map regimes
        self.router.map_regime_to_strategy(RegimeLabel.BULL, "momentum")
        self.router.map_regime_to_strategy(RegimeLabel.BEAR, "momentum")
        self.router.map_regime_to_strategy(RegimeLabel.CHOP, "mean_reversion")

        # State
        self.open_positions: Dict[str, OpenPosition] = {}
        self.closed_trades: List[Trade] = []
        self.equity_curve: List[EquityPoint] = []
        self.current_equity = self.config.initial_capital
        self.current_cash = self.config.initial_capital

        logger.info(f"BacktestRunner initialized with seed={self.config.random_seed}")

    def run(
        self,
        ohlcv_data: Dict[str, pd.DataFrame],
        pairs: List[str],
        timeframe: str = "5m",
        lookback_days: int = 720,
    ) -> BacktestResult:
        """
        Run backtest on historical data.

        Args:
            ohlcv_data: Dict mapping pair -> OHLCV DataFrame
            pairs: List of trading pairs to backtest
            timeframe: Timeframe (e.g., "5m", "1h")
            lookback_days: Number of days to backtest

        Returns:
            BacktestResult with metrics and equity curve

        Raises:
            ValueError: If data is invalid or DD threshold exceeded
        """
        logger.info(f"Starting backtest: pairs={pairs}, timeframe={timeframe}, lookback={lookback_days}d")

        # Validate data
        for pair in pairs:
            if pair not in ohlcv_data:
                raise ValueError(f"Missing OHLCV data for {pair}")

            df = ohlcv_data[pair]
            if len(df) < 100:
                raise ValueError(f"Insufficient data for {pair}: {len(df)} bars < 100")

        # Get date range
        start_date = min(df["timestamp"].iloc[0] for df in ohlcv_data.values())
        end_date = max(df["timestamp"].iloc[-1] for df in ohlcv_data.values())

        logger.info(f"Date range: {start_date} to {end_date}")

        # Replay bar-by-bar
        self._replay_bars(ohlcv_data, pairs, timeframe)

        # Close any remaining open positions
        self._close_all_positions(end_date)

        # Calculate metrics
        metrics = MetricsCalculator.calculate(
            trades=self.closed_trades,
            equity_curve=self.equity_curve,
            initial_capital=self.config.initial_capital,
        )

        # Check DD threshold (fail fast)
        if metrics.max_drawdown > self.config.max_drawdown_threshold:
            logger.error(
                f"FAIL: Max drawdown {metrics.max_drawdown:.2f}% exceeds "
                f"threshold {self.config.max_drawdown_threshold:.2f}%"
            )
            raise ValueError(
                f"Max drawdown {metrics.max_drawdown:.2f}% > "
                f"threshold {self.config.max_drawdown_threshold:.2f}%"
            )

        logger.info("Backtest completed successfully")
        logger.info(f"Total return: {metrics.total_return_pct:.2f}%")
        logger.info(f"Max drawdown: {metrics.max_drawdown:.2f}%")
        logger.info(f"Sharpe ratio: {metrics.sharpe_ratio:.2f}")
        logger.info(f"Profit factor: {metrics.profit_factor:.2f}")

        return BacktestResult(
            metrics=metrics,
            trades=self.closed_trades,
            equity_curve=self.equity_curve,
            config=self.config,
            pairs=pairs,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
        )

    def _replay_bars(
        self,
        ohlcv_data: Dict[str, pd.DataFrame],
        pairs: List[str],
        timeframe: str,
    ) -> None:
        """
        Replay bars chronologically across all pairs.

        Args:
            ohlcv_data: Dict mapping pair -> OHLCV DataFrame
            pairs: List of pairs to trade
            timeframe: Timeframe
        """
        # Merge all data with pair label
        all_bars = []
        for pair in pairs:
            df = ohlcv_data[pair].copy()
            df["pair"] = pair
            all_bars.append(df)

        combined = pd.concat(all_bars, ignore_index=True)
        combined = combined.sort_values("timestamp").reset_index(drop=True)

        logger.info(f"Replaying {len(combined)} bars...")

        # Process each bar
        for idx, row in combined.iterrows():
            pair = row["pair"]
            timestamp = row["timestamp"]

            # Check stop loss / take profit for open positions
            self._check_exits(pair, row)

            # Get OHLCV window for this pair (up to current bar)
            pair_data = ohlcv_data[pair]
            current_idx = pair_data[pair_data["timestamp"] == timestamp].index[0]
            ohlcv_window = pair_data.iloc[:current_idx+1]

            # Skip if insufficient data
            if len(ohlcv_window) < 100:
                continue

            # Process tick
            self._process_bar(pair, ohlcv_window, timeframe, row)

            # Record equity point
            self._record_equity_point(timestamp)

            # Log progress
            if idx % 1000 == 0:
                logger.debug(f"Processed {idx}/{len(combined)} bars, equity=${self.current_equity:.2f}")

    def _process_bar(
        self,
        pair: str,
        ohlcv_df: pd.DataFrame,
        timeframe: str,
        current_bar: pd.Series,
    ) -> None:
        """
        Process single bar through engine.

        Args:
            pair: Trading pair
            ohlcv_df: OHLCV data up to current bar
            timeframe: Timeframe
            current_bar: Current bar data
        """
        # Skip if already in position for this pair
        if pair in self.open_positions:
            return

        # Detect regime
        regime_tick = self.regime_detector.detect(ohlcv_df, timeframe)

        # Create market snapshot
        snapshot = MarketSnapshot(
            symbol=pair,
            timeframe=timeframe,
            timestamp_ms=int(current_bar["timestamp"].timestamp() * 1000),
            mid_price=float(current_bar["close"]),
            spread_bps=float(self.config.slippage_bps),  # Use slippage as spread proxy
            volume_24h=float(ohlcv_df["volume"].iloc[-24:].sum()) if len(ohlcv_df) >= 24 else 0.0,
        )

        # Route to strategy
        signal_spec = self.router.route(regime_tick, snapshot, ohlcv_df)

        if not signal_spec:
            return

        # ML confidence filter (if enabled)
        if self.ml_predictor:
            ml_result = self.ml_predictor.predict(snapshot, ohlcv_df, signal_spec.side)

            if not self.ml_predictor.should_trade(ml_result):
                logger.debug(
                    f"{pair}: ML filter rejected signal (confidence={ml_result.confidence:.3f} < "
                    f"{self.config.ml_config.min_alignment_confidence:.3f})"
                )
                return

            logger.debug(
                f"{pair}: ML filter passed (confidence={ml_result.confidence:.3f}, "
                f"components={ml_result.components})"
            )

        # Size position via risk manager
        signal_input = SignalInput(
            signal_id=signal_spec.signal_id,
            symbol=signal_spec.symbol,
            side=signal_spec.side,
            entry_price=signal_spec.entry_price,
            stop_loss=signal_spec.stop_loss,
            take_profit=signal_spec.take_profit,
            confidence=signal_spec.confidence,
        )

        position_size = self.risk_manager.size_position(signal_input, self.current_equity)

        if not position_size.allowed:
            return

        # Execute entry (simulate)
        self._enter_position(
            pair=pair,
            side=signal_spec.side,
            entry_time=current_bar["timestamp"],
            entry_price=signal_spec.entry_price,
            size=position_size.size,
            stop_loss=signal_spec.stop_loss,
            take_profit=signal_spec.take_profit,
            strategy=signal_spec.strategy,
        )

    def _enter_position(
        self,
        pair: str,
        side: str,
        entry_time: datetime,
        entry_price: Decimal,
        size: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal,
        strategy: str,
    ) -> None:
        """
        Enter position (simulated).

        Args:
            pair: Trading pair
            side: Trade direction
            entry_time: Entry timestamp
            entry_price: Entry price
            size: Position size
            stop_loss: Stop loss price
            take_profit: Take profit price
            strategy: Strategy name
        """
        # Apply slippage
        slippage_factor = Decimal("1") + (self.config.slippage_bps / Decimal("10000"))
        if side == "long":
            adjusted_entry = entry_price * slippage_factor
        else:
            adjusted_entry = entry_price / slippage_factor

        # Calculate cost
        notional = adjusted_entry * size
        entry_fee = notional * (self.config.fee_bps / Decimal("10000"))
        total_cost = notional + entry_fee

        # Check if sufficient cash
        if total_cost > self.current_cash:
            logger.debug(f"Insufficient cash for {pair} entry: need ${total_cost:.2f}, have ${self.current_cash:.2f}")
            return

        # Deduct from cash
        self.current_cash -= total_cost

        # Record position
        position = OpenPosition(
            pair=pair,
            side=side,
            entry_time=entry_time,
            entry_price=adjusted_entry,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=strategy,
        )

        self.open_positions[pair] = position

        logger.debug(
            f"ENTRY: {pair} {side} {size:.8f} @ ${adjusted_entry:.2f} "
            f"(SL=${stop_loss:.2f}, TP=${take_profit:.2f})"
        )

    def _check_exits(self, pair: str, bar: pd.Series) -> None:
        """
        Check if open positions hit stop loss or take profit.

        Args:
            pair: Trading pair
            bar: Current bar data
        """
        if pair not in self.open_positions:
            return

        position = self.open_positions[pair]
        high = Decimal(str(bar["high"]))
        low = Decimal(str(bar["low"]))
        close = Decimal(str(bar["close"]))
        timestamp = bar["timestamp"]

        # Check stop loss and take profit
        exit_price = None
        exit_reason = None

        if position.side == "long":
            # Check stop loss (low)
            if low <= position.stop_loss:
                exit_price = position.stop_loss
                exit_reason = "stop_loss"
            # Check take profit (high)
            elif high >= position.take_profit:
                exit_price = position.take_profit
                exit_reason = "take_profit"

        else:  # short
            # Check stop loss (high)
            if high >= position.stop_loss:
                exit_price = position.stop_loss
                exit_reason = "stop_loss"
            # Check take profit (low)
            elif low <= position.take_profit:
                exit_price = position.take_profit
                exit_reason = "take_profit"

        if exit_price:
            self._exit_position(pair, exit_price, timestamp, exit_reason)

    def _exit_position(
        self,
        pair: str,
        exit_price: Decimal,
        exit_time: datetime,
        reason: str,
    ) -> None:
        """
        Exit position (simulated).

        Args:
            pair: Trading pair
            exit_price: Exit price
            exit_time: Exit timestamp
            reason: Exit reason
        """
        position = self.open_positions.pop(pair)

        # Apply slippage
        slippage_factor = Decimal("1") + (self.config.slippage_bps / Decimal("10000"))
        if position.side == "long":
            adjusted_exit = exit_price / slippage_factor
        else:
            adjusted_exit = exit_price * slippage_factor

        # Calculate P&L
        notional = adjusted_exit * position.size
        exit_fee = notional * (self.config.fee_bps / Decimal("10000"))

        if position.side == "long":
            pnl = (adjusted_exit - position.entry_price) * position.size - exit_fee
        else:
            pnl = (position.entry_price - adjusted_exit) * position.size - exit_fee

        pnl_pct = pnl / (position.entry_price * position.size) * Decimal("100")

        # Add proceeds to cash
        self.current_cash += notional - exit_fee

        # Record trade
        trade = Trade(
            entry_time=position.entry_time,
            exit_time=exit_time,
            pair=pair,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=adjusted_exit,
            size=position.size,
            pnl=pnl,
            pnl_pct=pnl_pct,
            fees=exit_fee + (position.entry_price * position.size * self.config.fee_bps / Decimal("10000")),
            strategy=position.strategy,
        )

        self.closed_trades.append(trade)

        logger.debug(
            f"EXIT ({reason}): {pair} {position.side} {position.size:.8f} @ ${adjusted_exit:.2f}, "
            f"P&L=${pnl:.2f} ({pnl_pct:.2f}%)"
        )

    def _close_all_positions(self, timestamp: datetime) -> None:
        """
        Close all open positions at end of backtest.

        Args:
            timestamp: Closing timestamp
        """
        pairs_to_close = list(self.open_positions.keys())

        for pair in pairs_to_close:
            position = self.open_positions[pair]
            # Use entry price as proxy close price
            self._exit_position(pair, position.entry_price, timestamp, "end_of_backtest")

    def _record_equity_point(self, timestamp: datetime) -> None:
        """
        Record equity curve point.

        Args:
            timestamp: Current timestamp
        """
        # Calculate position value
        position_value = sum(
            pos.entry_price * pos.size for pos in self.open_positions.values()
        )

        # Total equity
        total_equity = self.current_cash + position_value

        # Cumulative P&L
        cum_pnl = total_equity - self.config.initial_capital

        point = EquityPoint(
            timestamp=timestamp,
            equity=total_equity,
            cash=self.current_cash,
            position_value=position_value,
            pnl=cum_pnl,
        )

        self.equity_curve.append(point)
        self.current_equity = total_equity


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "BacktestConfig",
    "BacktestRunner",
    "BacktestResult",
]
