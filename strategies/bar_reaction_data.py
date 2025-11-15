"""
Market Data Plumbing for bar_reaction_5m Strategy

Provides 5-minute bar sourcing, feature calculation, and microstructure metrics.

Components:
- C1: 5m bars source (native OHLCV + 1m rollup fallback)
- C2: Feature calculation (ATR, move_bps)
- C3: Liquidity & spread (rolling notional, spread proxy)

Environment:
- Conda env: crypto-bot
- Redis: kraken:ohlc:5m:{PAIR} streams (TLS cloud)
- Fallback: 1m → 5m aggregation for backtests

Reference: PRD_AGENTIC.md
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# =============================================================================
# C1 — 5m Bars Source
# =============================================================================

class Bars5mSource:
    """
    5-minute bar source with native OHLCV support and 1m rollup fallback.

    Preferred: Native kraken:ohlc:5m:{PAIR} from Redis
    Fallback: Roll up 1m bars into 5m for backtests

    Example:
        >>> source = Bars5mSource()
        >>> df_5m = source.get_5m_bars(df_1m, use_rollup=True)
        >>> print(f"Rolled up {len(df_1m)} 1m bars to {len(df_5m)} 5m bars")
    """

    def __init__(self):
        """Initialize 5m bars source."""
        self.logger = logging.getLogger(__name__)

    def get_native_5m_bars(
        self,
        symbol: str,
        start_ts: int,
        end_ts: int,
        redis_client=None
    ) -> Optional[pd.DataFrame]:
        """
        Fetch native 5m bars from Redis stream.

        Stream key format: kraken:ohlc:5m:{PAIR}
        Example: kraken:ohlc:5m:BTCUSD

        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            start_ts: Start timestamp (milliseconds)
            end_ts: End timestamp (milliseconds)
            redis_client: Redis client (optional, for live mode)

        Returns:
            DataFrame with OHLCV data or None if unavailable

        Note:
            If redis_client is None, returns None (backtest fallback)
        """
        if redis_client is None:
            self.logger.debug("No Redis client, will use rollup fallback")
            return None

        try:
            # Normalize symbol for Redis key (BTC/USD → BTCUSD)
            pair_key = symbol.replace("/", "").replace("-", "")
            stream_key = f"kraken:ohlc:5m:{pair_key}"

            # Fetch from Redis stream (implementation depends on your Redis setup)
            # This is a placeholder - actual implementation would use XRANGE
            self.logger.info(f"Fetching native 5m bars from {stream_key}")

            # TODO: Implement actual Redis XRANGE fetch
            # data = redis_client.xrange(stream_key, start_ts, end_ts)
            # df = self._parse_redis_ohlcv(data)

            return None  # Placeholder - returns None to trigger rollup fallback

        except Exception as e:
            self.logger.warning(f"Failed to fetch native 5m bars: {e}, using rollup")
            return None

    def rollup_1m_to_5m(self, df_1m: pd.DataFrame) -> pd.DataFrame:
        """
        Roll up 1-minute bars into 5-minute bars.

        Aggregation rules:
        - timestamp: First timestamp of 5m period (00:00, 00:05, 00:10, etc.)
        - open: First open in 5m period
        - high: Max high in 5m period
        - low: Min low in 5m period
        - close: Last close in 5m period
        - volume: Sum of volume in 5m period

        Args:
            df_1m: 1-minute OHLCV DataFrame with columns:
                   [timestamp, open, high, low, close, volume]

        Returns:
            5-minute OHLCV DataFrame

        Example:
            >>> df_1m = pd.DataFrame({
            ...     'timestamp': pd.date_range('2024-01-01', periods=10, freq='1min'),
            ...     'open': [50000, 50010, 50020, 50030, 50040, 50050, 50060, 50070, 50080, 50090],
            ...     'high': [50010, 50020, 50030, 50040, 50050, 50060, 50070, 50080, 50090, 50100],
            ...     'low': [49990, 50000, 50010, 50020, 50030, 50040, 50050, 50060, 50070, 50080],
            ...     'close': [50005, 50015, 50025, 50035, 50045, 50055, 50065, 50075, 50085, 50095],
            ...     'volume': [10] * 10
            ... })
            >>> df_5m = Bars5mSource().rollup_1m_to_5m(df_1m)
            >>> len(df_5m)
            2  # 10 minutes = 2 five-minute bars
        """
        if df_1m.empty:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # Ensure timestamp is datetime
        df = df_1m.copy()
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])

        # Set timestamp as index for resampling
        df.set_index('timestamp', inplace=True)

        # Resample to 5-minute bars
        # '5min' = 5 minutes, label='left' = use start of interval
        df_5m = df.resample('5min', label='left').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

        # Reset index to get timestamp as column
        df_5m.reset_index(inplace=True)

        self.logger.debug(f"Rolled up {len(df)} 1m bars -> {len(df_5m)} 5m bars")

        return df_5m

    def get_5m_bars(
        self,
        symbol: str,
        df_1m: Optional[pd.DataFrame] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        redis_client=None,
        use_rollup: bool = True
    ) -> pd.DataFrame:
        """
        Get 5m bars with automatic fallback to rollup.

        Priority:
        1. Native kraken:ohlc:5m:{PAIR} from Redis (if available)
        2. Rollup from 1m bars (if df_1m provided)

        Args:
            symbol: Trading pair
            df_1m: 1-minute bars for rollup fallback
            start_ts: Start timestamp (milliseconds)
            end_ts: End timestamp (milliseconds)
            redis_client: Redis client for native fetch
            use_rollup: Enable rollup fallback (default: True)

        Returns:
            5-minute OHLCV DataFrame

        Raises:
            ValueError: If no data source available
        """
        # Try native 5m bars first
        if redis_client is not None and start_ts is not None and end_ts is not None:
            df_native = self.get_native_5m_bars(symbol, start_ts, end_ts, redis_client)
            if df_native is not None and not df_native.empty:
                self.logger.info(f"Using native 5m bars for {symbol}")
                return df_native

        # Fallback to rollup
        if use_rollup and df_1m is not None and not df_1m.empty:
            self.logger.info(f"Using 1m→5m rollup for {symbol}")
            return self.rollup_1m_to_5m(df_1m)

        raise ValueError(
            f"No 5m bar source available for {symbol}. "
            "Provide either redis_client or df_1m for rollup."
        )


# =============================================================================
# C2 — Feature Calculation
# =============================================================================

class BarReactionFeatures:
    """
    Feature calculator for bar_reaction_5m strategy.

    Features:
    - ATR(14) on 5m bars
    - atr_pct: ATR/close * 100 (percentage)
    - move_bps: Bar move in basis points (1bps = 0.01%)
      - open_to_close: (close - open) / open * 10000
      - prev_close_to_close: (close - prev_close) / prev_close * 10000

    Example:
        >>> calc = BarReactionFeatures()
        >>> df_with_features = calc.calculate_all_features(df_5m)
        >>> print(df_with_features[['atr', 'atr_pct', 'move_bps_oc', 'move_bps_pcc']])
    """

    def __init__(self, atr_period: int = 14):
        """
        Initialize feature calculator.

        Args:
            atr_period: ATR lookback period (default: 14)
        """
        self.atr_period = atr_period
        self.logger = logging.getLogger(__name__)

    def calculate_atr(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate Average True Range (ATR).

        ATR = Average of True Range over N periods
        True Range = max(H-L, |H-C_prev|, |L-C_prev|)

        Args:
            df: OHLCV DataFrame with columns [open, high, low, close, volume]

        Returns:
            Series with ATR values

        Example:
            >>> df = pd.DataFrame({
            ...     'high': [101, 103, 102, 105],
            ...     'low': [99, 100, 98, 101],
            ...     'close': [100, 102, 101, 104]
            ... })
            >>> atr = BarReactionFeatures().calculate_atr(df)
            >>> atr.iloc[-1]  # Latest ATR value
        """
        if len(df) < self.atr_period + 1:
            self.logger.warning(
                f"Insufficient data for ATR: need {self.atr_period + 1}, got {len(df)}"
            )
            return pd.Series([np.nan] * len(df), index=df.index)

        high = df['high'].values
        low = df['low'].values
        close = df['close'].values

        # Calculate True Range
        tr = []
        for i in range(1, len(df)):
            h_l = high[i] - low[i]
            h_pc = abs(high[i] - close[i-1])
            l_pc = abs(low[i] - close[i-1])
            tr.append(max(h_l, h_pc, l_pc))

        # First TR is just high-low
        tr.insert(0, high[0] - low[0])

        # Calculate ATR as rolling mean of TR
        tr_series = pd.Series(tr, index=df.index)
        atr = tr_series.rolling(window=self.atr_period, min_periods=self.atr_period).mean()

        return atr

    def calculate_atr_pct(self, df: pd.DataFrame, atr: pd.Series) -> pd.Series:
        """
        Calculate ATR as percentage of close price.

        atr_pct = (ATR / close) * 100

        Args:
            df: OHLCV DataFrame
            atr: ATR series from calculate_atr()

        Returns:
            Series with atr_pct values

        Example:
            >>> df = pd.DataFrame({'close': [50000, 50500, 51000]})
            >>> atr = pd.Series([200, 210, 220], index=df.index)
            >>> atr_pct = BarReactionFeatures().calculate_atr_pct(df, atr)
            >>> atr_pct.iloc[-1]
            0.431  # 220 / 51000 * 100 ≈ 0.43%
        """
        close = df['close'].values
        atr_pct = (atr / close) * 100
        return atr_pct

    def calculate_move_bps_open_to_close(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate bar move from open to close in basis points.

        move_bps_oc = (close - open) / open * 10000

        1 bps = 0.01% = 0.0001
        10000 bps = 100%

        Args:
            df: OHLCV DataFrame with open and close columns

        Returns:
            Series with move_bps values

        Example:
            >>> df = pd.DataFrame({
            ...     'open': [50000, 50500],
            ...     'close': [50060, 50440]
            ... })
            >>> move_bps = BarReactionFeatures().calculate_move_bps_open_to_close(df)
            >>> move_bps.iloc[0]
            12.0  # (50060 - 50000) / 50000 * 10000 = 12 bps
        """
        open_price = df['open'].values
        close_price = df['close'].values

        # Avoid division by zero
        with np.errstate(divide='ignore', invalid='ignore'):
            move_bps = (close_price - open_price) / open_price * 10000

        # Replace inf/nan with 0
        move_bps = np.where(np.isfinite(move_bps), move_bps, 0)

        return pd.Series(move_bps, index=df.index)

    def calculate_move_bps_prev_close_to_close(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate bar move from previous close to current close in basis points.

        move_bps_pcc = (close - prev_close) / prev_close * 10000

        Args:
            df: OHLCV DataFrame with close column

        Returns:
            Series with move_bps values (first value is NaN)

        Example:
            >>> df = pd.DataFrame({'close': [50000, 50060, 50120]})
            >>> move_bps = BarReactionFeatures().calculate_move_bps_prev_close_to_close(df)
            >>> move_bps.iloc[1]
            12.0  # (50060 - 50000) / 50000 * 10000 = 12 bps
        """
        close_price = df['close'].values
        prev_close = np.roll(close_price, 1)
        prev_close[0] = np.nan  # First bar has no previous close

        # Avoid division by zero
        with np.errstate(divide='ignore', invalid='ignore'):
            move_bps = (close_price - prev_close) / prev_close * 10000

        # Replace inf with nan (will handle later)
        move_bps = np.where(np.isfinite(move_bps), move_bps, np.nan)

        return pd.Series(move_bps, index=df.index)

    def calculate_all_features(
        self,
        df: pd.DataFrame,
        trigger_mode: str = "open_to_close"
    ) -> pd.DataFrame:
        """
        Calculate all features for bar_reaction_5m strategy.

        Adds columns:
        - atr: Average True Range (14 periods)
        - atr_pct: ATR as percentage of close
        - move_bps: Bar move in basis points (based on trigger_mode)

        Args:
            df: OHLCV DataFrame
            trigger_mode: "open_to_close" or "prev_close_to_close"

        Returns:
            DataFrame with added feature columns

        Example:
            >>> df_with_features = calc.calculate_all_features(df_5m, "open_to_close")
            >>> print(df_with_features[['close', 'atr', 'atr_pct', 'move_bps']].tail())
        """
        df_features = df.copy()

        # Calculate ATR
        atr = self.calculate_atr(df_features)
        df_features['atr'] = atr

        # Calculate ATR%
        atr_pct = self.calculate_atr_pct(df_features, atr)
        df_features['atr_pct'] = atr_pct

        # Calculate move_bps based on trigger mode
        if trigger_mode == "open_to_close":
            move_bps = self.calculate_move_bps_open_to_close(df_features)
        elif trigger_mode == "prev_close_to_close":
            move_bps = self.calculate_move_bps_prev_close_to_close(df_features)
        else:
            raise ValueError(
                f"Invalid trigger_mode: {trigger_mode}. "
                "Must be 'open_to_close' or 'prev_close_to_close'"
            )

        df_features['move_bps'] = move_bps

        # Also add both versions for reference
        df_features['move_bps_oc'] = self.calculate_move_bps_open_to_close(df_features)
        df_features['move_bps_pcc'] = self.calculate_move_bps_prev_close_to_close(df_features)

        self.logger.debug(
            f"Calculated features: ATR (period={self.atr_period}), "
            f"move_bps (mode={trigger_mode})"
        )

        return df_features


# =============================================================================
# C3 — Liquidity & Spread
# =============================================================================

class MicrostructureMetrics:
    """
    Microstructure metrics for bar_reaction_5m strategy.

    Metrics:
    - Rolling 5m notional: sum(volume * vwap) of last bar
    - Spread bps: bid-ask spread in basis points
      - Live: (best_ask - best_bid) / mid * 10000
      - Backtest proxy: max((high - low) / close * 10000 * 0.35, 2)

    Example:
        >>> metrics = MicrostructureMetrics()
        >>> spread_bps = metrics.estimate_spread_bps_backtest(df_5m)
        >>> notional = metrics.calculate_rolling_notional(df_5m)
    """

    def __init__(self):
        """Initialize microstructure metrics calculator."""
        self.logger = logging.getLogger(__name__)

    def calculate_rolling_notional(
        self,
        df: pd.DataFrame,
        use_vwap: bool = False
    ) -> pd.Series:
        """
        Calculate rolling 5m notional volume.

        Rolling notional = sum(volume * price) for last bar

        Args:
            df: OHLCV DataFrame
            use_vwap: Use VWAP if available, else use close as proxy

        Returns:
            Series with rolling notional in USD

        Example:
            >>> df = pd.DataFrame({
            ...     'volume': [100, 150, 200],
            ...     'close': [50000, 50500, 51000]
            ... })
            >>> notional = MicrostructureMetrics().calculate_rolling_notional(df)
            >>> notional.iloc[-1]
            10200000  # 200 * 51000
        """
        volume = df['volume'].values

        # Use VWAP if available, else use close as proxy
        if use_vwap and 'vwap' in df.columns:
            price = df['vwap'].values
        else:
            price = df['close'].values

        # Notional = volume * price for each bar
        notional = volume * price

        return pd.Series(notional, index=df.index)

    def estimate_spread_bps_live(
        self,
        best_bid: float,
        best_ask: float
    ) -> float:
        """
        Calculate spread in basis points from live bid/ask.

        spread_bps = (best_ask - best_bid) / mid * 10000
        where mid = (best_bid + best_ask) / 2

        Args:
            best_bid: Best bid price
            best_ask: Best ask price

        Returns:
            Spread in basis points

        Example:
            >>> MicrostructureMetrics().estimate_spread_bps_live(49999, 50001)
            4.0  # (50001 - 49999) / 50000 * 10000 = 4 bps
        """
        if best_bid <= 0 or best_ask <= 0:
            self.logger.warning(f"Invalid bid/ask: bid={best_bid}, ask={best_ask}")
            return float('inf')

        if best_ask <= best_bid:
            self.logger.warning(f"Crossed market: bid={best_bid} >= ask={best_ask}")
            return 0.0

        mid = (best_bid + best_ask) / 2
        spread_bps = (best_ask - best_bid) / mid * 10000

        return spread_bps

    def estimate_spread_bps_backtest(
        self,
        df: pd.DataFrame,
        conservative_factor: float = 0.35,
        min_spread_bps: float = 2.0
    ) -> pd.Series:
        """
        Estimate spread in basis points for backtesting (conservative proxy).

        Proxy formula:
        spread_bps = max((high - low) / close * 10000 * conservative_factor, min_spread_bps)

        The conservative_factor (default 0.35) accounts for:
        - High-low is the full bar range (includes wicks)
        - Actual spread is typically much tighter
        - 35% of high-low range is a conservative estimate

        Args:
            df: OHLCV DataFrame
            conservative_factor: Multiplier for high-low range (default: 0.35)
            min_spread_bps: Minimum spread to assume (default: 2 bps)

        Returns:
            Series with estimated spread in basis points

        Example:
            >>> df = pd.DataFrame({
            ...     'high': [50100, 50600],
            ...     'low': [49900, 50400],
            ...     'close': [50000, 50500]
            ... })
            >>> spread_bps = MicrostructureMetrics().estimate_spread_bps_backtest(df)
            >>> spread_bps.iloc[0]
            14.0  # max((50100-49900)/50000*10000*0.35, 2) = max(14, 2) = 14 bps
        """
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values

        # Avoid division by zero
        with np.errstate(divide='ignore', invalid='ignore'):
            high_low_bps = (high - low) / close * 10000

        # Apply conservative factor and minimum
        spread_bps = np.maximum(
            high_low_bps * conservative_factor,
            min_spread_bps
        )

        # Replace inf/nan with min_spread_bps
        spread_bps = np.where(np.isfinite(spread_bps), spread_bps, min_spread_bps)

        return pd.Series(spread_bps, index=df.index)


# =============================================================================
# UNIFIED INTERFACE
# =============================================================================

class BarReactionDataPipeline:
    """
    Unified data pipeline for bar_reaction_5m strategy.

    Combines:
    - C1: 5m bars source (native + rollup)
    - C2: Feature calculation (ATR, move_bps)
    - C3: Microstructure metrics (liquidity, spread)

    Example:
        >>> pipeline = BarReactionDataPipeline()
        >>> df_enriched = pipeline.prepare_data(
        ...     symbol="BTC/USD",
        ...     df_1m=df_1m,
        ...     trigger_mode="open_to_close"
        ... )
        >>> print(df_enriched.columns)
        ['timestamp', 'open', 'high', 'low', 'close', 'volume',
         'atr', 'atr_pct', 'move_bps', 'notional_usd', 'spread_bps']
    """

    def __init__(self, atr_period: int = 14):
        """
        Initialize data pipeline.

        Args:
            atr_period: ATR lookback period (default: 14)
        """
        self.bars_source = Bars5mSource()
        self.features = BarReactionFeatures(atr_period=atr_period)
        self.microstructure = MicrostructureMetrics()
        self.logger = logging.getLogger(__name__)

    def prepare_data(
        self,
        symbol: str,
        df_1m: Optional[pd.DataFrame] = None,
        trigger_mode: str = "open_to_close",
        redis_client=None,
        use_backtest_spread: bool = True
    ) -> pd.DataFrame:
        """
        Prepare complete dataset for bar_reaction_5m strategy.

        Pipeline:
        1. Get 5m bars (native or rollup)
        2. Calculate features (ATR, move_bps)
        3. Add microstructure metrics (liquidity, spread)

        Args:
            symbol: Trading pair
            df_1m: 1-minute bars for rollup
            trigger_mode: "open_to_close" or "prev_close_to_close"
            redis_client: Redis client for native 5m bars
            use_backtest_spread: Use backtest spread proxy (default: True)

        Returns:
            Enriched DataFrame with all features and metrics

        Example:
            >>> df_enriched = pipeline.prepare_data("BTC/USD", df_1m=df_1m)
            >>> df_enriched[['close', 'atr', 'move_bps', 'spread_bps']].tail()
        """
        # C1: Get 5m bars
        df_5m = self.bars_source.get_5m_bars(
            symbol=symbol,
            df_1m=df_1m,
            redis_client=redis_client,
            use_rollup=True
        )

        if df_5m.empty:
            raise ValueError(f"No 5m bars available for {symbol}")

        # C2: Calculate features
        df_features = self.features.calculate_all_features(
            df_5m,
            trigger_mode=trigger_mode
        )

        # C3: Add microstructure metrics
        # Rolling notional
        df_features['notional_usd'] = self.microstructure.calculate_rolling_notional(df_features)

        # Spread estimate
        if use_backtest_spread:
            df_features['spread_bps'] = self.microstructure.estimate_spread_bps_backtest(df_features)
        else:
            # For live trading, spread_bps would be populated from order book
            df_features['spread_bps'] = np.nan

        self.logger.info(
            f"Prepared {len(df_features)} bars for {symbol} "
            f"(trigger_mode={trigger_mode})"
        )

        return df_features


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test data pipeline with synthetic data"""
    import sys

    logging.basicConfig(level=logging.INFO)

    try:
        # Create synthetic 1m data
        np.random.seed(42)
        n_bars = 20  # 20 minutes = 4 five-minute bars

        base_price = 50000
        price_changes = np.cumsum(np.random.randn(n_bars) * 10)
        closes = base_price + price_changes

        df_1m = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=n_bars, freq='1min'),
            'open': closes - np.random.uniform(5, 15, n_bars),
            'high': closes + np.random.uniform(10, 30, n_bars),
            'low': closes - np.random.uniform(10, 30, n_bars),
            'close': closes,
            'volume': np.random.uniform(5, 15, n_bars)
        })

        print("=== Bar Reaction Data Pipeline Self-Check ===\n")

        # Test C1: Bars source
        print("C1 — 5m Bars Source")
        bars_source = Bars5mSource()
        df_5m = bars_source.rollup_1m_to_5m(df_1m)
        print(f"  Rolled up {len(df_1m)} 1m bars -> {len(df_5m)} 5m bars")
        assert len(df_5m) == 4, f"Expected 4 bars, got {len(df_5m)}"
        print("  [OK] Rollup working\n")

        # Test C2: Features
        print("C2 — Feature Calculation")
        features = BarReactionFeatures(atr_period=3)  # Short period for test
        df_features = features.calculate_all_features(df_5m, "open_to_close")
        print(f"  Columns: {list(df_features.columns)}")
        print(f"  Latest ATR: {df_features['atr'].iloc[-1]:.2f}")
        print(f"  Latest ATR%: {df_features['atr_pct'].iloc[-1]:.3f}%")
        print(f"  Latest move_bps (o-c): {df_features['move_bps_oc'].iloc[-1]:.2f} bps")
        print("  [OK] Features calculated\n")

        # Test C3: Microstructure
        print("C3 — Liquidity & Spread")
        metrics = MicrostructureMetrics()
        df_features['notional_usd'] = metrics.calculate_rolling_notional(df_features)
        df_features['spread_bps'] = metrics.estimate_spread_bps_backtest(df_features)
        print(f"  Latest notional: ${df_features['notional_usd'].iloc[-1]:,.0f}")
        print(f"  Latest spread: {df_features['spread_bps'].iloc[-1]:.2f} bps")
        print("  [OK] Microstructure metrics calculated\n")

        # Test unified pipeline
        print("Unified Pipeline Test")
        pipeline = BarReactionDataPipeline(atr_period=3)
        df_enriched = pipeline.prepare_data("BTC/USD", df_1m=df_1m)
        print(f"  Final shape: {df_enriched.shape}")
        print(f"  Columns: {list(df_enriched.columns)}")
        print("\n  Sample row:")
        print(df_enriched[['close', 'atr', 'atr_pct', 'move_bps', 'spread_bps']].iloc[-1])
        print("\n  [OK] Pipeline complete\n")

        print("="*50)
        print("PASS: All components working")
        print("="*50)

    except Exception as e:
        print(f"\nFAIL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
