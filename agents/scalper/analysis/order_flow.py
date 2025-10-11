"""
Advanced order flow analysis for high-frequency scalping operations.

This module provides comprehensive order flow analysis capabilities for the scalping
system, analyzing trade direction, volume patterns, and market microstructure signals
to identify profitable trading opportunities and market conditions.

Features:
- Real-time trade direction classification
- Volume imbalance analysis
- Large trade detection and tracking
- Market microstructure analysis
- Flow signal generation
- Performance monitoring and metrics
- Multi-timeframe analysis
- Whale activity detection

This module provides the core order flow analysis capabilities for the scalping
system, enabling intelligent trade execution and market timing decisions.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Custom imports (kept, but guarded at runtime)
try:
    from ..infra.logger import ScalperLogger  # provides .get_logger(name)
except Exception:  # pragma: no cover - optional dependency
    ScalperLogger = None  # type: ignore

try:
    from ..infra.metrics import MetricsCollector  # provides async .emit_metrics(dict)
except Exception:  # pragma: no cover - optional dependency
    MetricsCollector = None  # type: ignore


class TradeDirection(Enum):
    """Trade direction classification"""

    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


class FlowSignal(Enum):
    """Order flow signal types"""

    STRONG_BUY = "strong_buy"
    WEAK_BUY = "weak_buy"
    NEUTRAL = "neutral"
    WEAK_SELL = "weak_sell"
    STRONG_SELL = "strong_sell"


@dataclass
class TradeEvent:
    """Individual trade event"""

    timestamp: float
    pair: str
    price: float
    volume: float
    direction: TradeDirection
    order_type: str  # 'market' or 'limit'

    # Derived fields
    notional_usd: float = field(init=False)

    def __post_init__(self) -> None:
        self.notional_usd = float(self.price) * float(self.volume)


@dataclass
class FlowMetrics:
    """Order flow metrics for a time window"""

    timestamp: float
    pair: str
    window_seconds: int

    # Volume metrics
    total_volume: float
    buy_volume: float
    sell_volume: float
    volume_imbalance: float  # (buy - sell) / (buy + sell)

    # Trade metrics
    total_trades: int
    buy_trades: int
    sell_trades: int
    trade_imbalance: float  # (buy_trades - sell_trades) / total_trades

    # Price metrics
    vwap: float
    price_change: float
    price_change_bps: float

    # Size analysis
    avg_trade_size: float
    large_trade_count: int
    large_trade_volume: float

    # Flow signals
    flow_signal: FlowSignal
    flow_strength: float  # 0-1, higher = stronger signal

    # Microstructure
    tick_direction_sum: int  # +1 for uptick, -1 for downtick
    price_improvement_events: int
    aggressive_trade_ratio: float


@dataclass
class OrderFlowConfig:
    """Configuration for order flow analysis"""

    # Window settings
    analysis_windows: List[int] = field(default_factory=lambda: [10, 30, 60, 300])  # seconds
    min_trades_per_window: int = 3

    # Size thresholds for Kraken BTC/USD
    large_trade_btc: float = 0.5
    block_trade_btc: float = 2.0
    whale_trade_btc: float = 10.0

    # Signal thresholds
    strong_imbalance_threshold: float = 0.7
    weak_imbalance_threshold: float = 0.3
    flow_strength_threshold: float = 0.6

    # Tick analysis
    tick_size_usd: float = 0.1  # Kraken BTC/USD tick size
    price_improvement_threshold_bps: float = 0.5

    # Performance
    max_trade_history: int = 10000
    update_frequency_ms: int = 100


class OrderFlowAnalyzer:
    """
    Production-grade order flow analyzer for Kraken scalping.

    Analyzes real-time trade data to identify:
    - Buy/sell pressure and imbalances
    - Large block trades and institutional activity
    - Price momentum and direction
    - Market microstructure signals
    """

    def __init__(self, config: Optional[OrderFlowConfig] = None) -> None:
        self.config = config or OrderFlowConfig()

        # Logger fallback if custom infra logger is not available
        if ScalperLogger is not None:
            self.logger = ScalperLogger().get_logger("order_flow")
        else:
            self.logger = logging.getLogger(__name__ + ".order_flow")

        # Metrics fallback to a no-op shim if not available
        if MetricsCollector is not None:
            self.metrics = MetricsCollector()
        else:

            class _NoopMetrics:  # pragma: no cover - optional dependency
                async def emit_metrics(self, *_: Any, **__: Any) -> None:
                    return

            self.metrics = _NoopMetrics()

        # Trade storage
        self.trades: Dict[str, deque[TradeEvent]] = defaultdict(
            lambda: deque(maxlen=self.config.max_trade_history)
        )

        # Flow metrics per window
        self.flow_metrics: Dict[str, Dict[int, FlowMetrics]] = defaultdict(dict)

        # Real-time state
        self.last_prices: Dict[str, float] = {}
        self.last_update: Dict[str, float] = {}

        # Performance tracking
        self._proc_times_ms: deque[float] = deque(maxlen=2000)
        self._proc_timestamps: deque[float] = deque(maxlen=2000)  # wall-clock seconds

    async def process_trade(self, trade_data: dict) -> Optional[TradeEvent]:
        """
        Process a single trade event.

        Args:
            trade_data: Trade data from WebSocket or API

        Returns:
            TradeEvent if processed successfully
        """
        t0 = time.perf_counter()
        wall_ts = time.time()

        try:
            # Extract trade information
            pair = str(trade_data.get("pair", ""))
            price = float(trade_data.get("price", 0.0))
            volume = float(trade_data.get("volume", 0.0))
            timestamp = float(trade_data.get("timestamp", wall_ts))
            side = (trade_data.get("side") or "").lower()
            order_type = (trade_data.get("order_type") or "unknown").lower()

            # Determine trade direction
            direction = self._classify_trade_direction(pair, price, side)

            # Create trade event
            trade_event = TradeEvent(
                timestamp=timestamp,
                pair=pair,
                price=price,
                volume=volume,
                direction=direction,
                order_type=order_type,
            )

            # Store trade
            self.trades[pair].append(trade_event)
            self.last_prices[pair] = price
            self.last_update[pair] = wall_ts

            # Update flow metrics for all windows
            await self._update_flow_metrics(pair)

            # Track performance
            processing_time_ms = (time.perf_counter() - t0) * 1000.0
            self._proc_times_ms.append(processing_time_ms)
            self._proc_timestamps.append(wall_ts)

            # Emit metrics (best-effort)
            await self._emit_trade_metrics(trade_event, processing_time_ms)

            return trade_event

        except Exception as e:
            self.logger.error(f"Error processing trade: {e}", exc_info=True)
            return None

    def _classify_trade_direction(self, pair: str, price: float, side: str) -> TradeDirection:
        """Classify trade direction using multiple methods"""

        # Method 1: Direct side indication (if available)
        if side:
            if side in {"b", "buy"}:
                return TradeDirection.BUY
            if side in {"s", "sell"}:
                return TradeDirection.SELL

        # Method 2: Tick rule (compare to last price)
        last_price = self.last_prices.get(pair)
        if last_price is not None:
            if price > last_price:
                return TradeDirection.BUY
            if price < last_price:
                return TradeDirection.SELL

        # Method 3: Quote rule would require L2 book; unknown otherwise
        return TradeDirection.UNKNOWN

    async def _update_flow_metrics(self, pair: str) -> None:
        """Update order flow metrics for all configured windows"""
        now = time.time()
        trades = list(self.trades[pair])
        if not trades:
            return

        for window_seconds in self.config.analysis_windows:
            cutoff = now - float(window_seconds)
            window_trades = [t for t in trades if t.timestamp >= cutoff]

            if len(window_trades) < self.config.min_trades_per_window:
                continue

            metrics = self._calculate_window_metrics(pair, window_trades, window_seconds)
            if metrics is None:
                continue

            self.flow_metrics[pair][window_seconds] = metrics
            await self._emit_flow_metrics(metrics)

    def _calculate_window_metrics(
        self, pair: str, trades: List[TradeEvent], window_seconds: int
    ) -> Optional[FlowMetrics]:
        """Calculate comprehensive flow metrics for a time window"""
        if not trades:
            return None

        ts = time.time()

        # Basic counts
        total_trades = len(trades)
        buy_trades = sum(1 for t in trades if t.direction == TradeDirection.BUY)
        sell_trades = sum(1 for t in trades if t.direction == TradeDirection.SELL)

        # Volume analysis
        total_volume = float(sum(t.volume for t in trades))
        buy_volume = float(sum(t.volume for t in trades if t.direction == TradeDirection.BUY))
        sell_volume = float(sum(t.volume for t in trades if t.direction == TradeDirection.SELL))

        # Imbalances
        denom_vol = (buy_volume + sell_volume) or 1e-8
        volume_imbalance = (buy_volume - sell_volume) / denom_vol

        denom_trd = total_trades or 1e-8
        trade_imbalance = (buy_trades - sell_trades) / denom_trd

        # VWAP calculation
        total_notional = float(sum(t.price * t.volume for t in trades))
        vwap = total_notional / total_volume if total_volume > 0.0 else 0.0

        # Price change (first to last trade price)
        if total_trades >= 2:
            price_change = trades[-1].price - trades[0].price
            price_change_bps = (
                (price_change / trades[0].price) * 10000.0 if trades[0].price else 0.0
            )
        else:
            price_change = 0.0
            price_change_bps = 0.0

        # Size analysis
        avg_trade_size = total_volume / total_trades if total_trades > 0 else 0.0
        large_trades = [t for t in trades if t.volume >= self.config.large_trade_btc]
        large_trade_count = len(large_trades)
        large_trade_volume = float(sum(t.volume for t in large_trades))

        # Tick direction & microstructure
        tick_direction_sum = 0
        price_improvement_events = 0
        aggressive_trades = 0

        for i, trade in enumerate(trades):
            if i > 0:
                prev_price = trades[i - 1].price
                if trade.price > prev_price:
                    tick_direction_sum += 1
                elif trade.price < prev_price:
                    tick_direction_sum -= 1

                # Price improvement detection (vs previous trade)
                if prev_price > 0:
                    price_diff_bps = abs(trade.price - prev_price) / prev_price * 10000.0
                    if price_diff_bps > self.config.price_improvement_threshold_bps:
                        price_improvement_events += 1

            if trade.order_type == "market":
                aggressive_trades += 1

        aggressive_trade_ratio = aggressive_trades / total_trades if total_trades > 0 else 0.0

        # Flow signal generation
        large_trade_ratio = (large_trade_volume / total_volume) if total_volume > 0 else 0.0
        flow_signal, flow_strength = self._generate_flow_signal(
            volume_imbalance, trade_imbalance, price_change_bps, large_trade_ratio
        )

        return FlowMetrics(
            timestamp=ts,
            pair=pair,
            window_seconds=window_seconds,
            total_volume=total_volume,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            volume_imbalance=volume_imbalance,
            total_trades=total_trades,
            buy_trades=buy_trades,
            sell_trades=sell_trades,
            trade_imbalance=trade_imbalance,
            vwap=vwap,
            price_change=float(price_change),
            price_change_bps=float(price_change_bps),
            avg_trade_size=float(avg_trade_size),
            large_trade_count=large_trade_count,
            large_trade_volume=large_trade_volume,
            flow_signal=flow_signal,
            flow_strength=float(flow_strength),
            tick_direction_sum=int(tick_direction_sum),
            price_improvement_events=int(price_improvement_events),
            aggressive_trade_ratio=float(aggressive_trade_ratio),
        )

    def _generate_flow_signal(
        self,
        volume_imbalance: float,
        trade_imbalance: float,
        price_change_bps: float,
        large_trade_ratio: float,
    ) -> Tuple[FlowSignal, float]:
        """Generate order flow signal and strength based on multiple factors"""
        # Weighted scoring in [-1, 1]
        volume_score = float(volume_imbalance)  # [-1, 1]
        trade_score = float(trade_imbalance)  # [-1, 1]
        price_score = float(np.tanh(price_change_bps / 10.0))  # smooth clamp
        size_score = float(large_trade_ratio * 2.0 - 1.0)  # map [0,1] -> [-1,1]

        flow_score = 0.4 * volume_score + 0.3 * trade_score + 0.2 * price_score + 0.1 * size_score

        flow_strength = min(1.0, max(0.0, abs(flow_score)))

        # Signal classification (symmetric thresholds)
        if flow_score >= self.config.strong_imbalance_threshold:
            return FlowSignal.STRONG_BUY, flow_strength
        if flow_score >= self.config.weak_imbalance_threshold:
            return FlowSignal.WEAK_BUY, flow_strength
        if flow_score <= -self.config.strong_imbalance_threshold:
            return FlowSignal.STRONG_SELL, flow_strength
        if flow_score <= -self.config.weak_imbalance_threshold:
            return FlowSignal.WEAK_SELL, flow_strength
        return FlowSignal.NEUTRAL, flow_strength

    async def _emit_trade_metrics(self, trade: TradeEvent, processing_time_ms: float) -> None:
        """Emit individual trade metrics (best-effort if metrics backend exists)"""
        pair_key = trade.pair.replace("/", "_").lower()
        metrics = {
            f"order_flow_trade_volume_{pair_key}": trade.volume,
            f"order_flow_trade_notional_{pair_key}": trade.notional_usd,
            "order_flow_processing_time_ms": processing_time_ms,
        }

        if trade.direction != TradeDirection.UNKNOWN:
            direction_key = trade.direction.value
            metrics[f"order_flow_{direction_key}_volume_{pair_key}"] = trade.volume

        # No-op if MetricsCollector is not available
        await self.metrics.emit_metrics(metrics)

    async def _emit_flow_metrics(self, flow_metrics: FlowMetrics) -> None:
        """Emit comprehensive flow metrics (best-effort)"""
        pair_key = flow_metrics.pair.replace("/", "_").lower()
        window_key = f"{flow_metrics.window_seconds}s"

        metrics = {
            f"order_flow_volume_imbalance_{pair_key}_{window_key}": flow_metrics.volume_imbalance,
            f"order_flow_trade_imbalance_{pair_key}_{window_key}": flow_metrics.trade_imbalance,
            f"order_flow_price_change_bps_{pair_key}_{window_key}": flow_metrics.price_change_bps,
            f"order_flow_total_volume_{pair_key}_{window_key}": flow_metrics.total_volume,
            f"order_flow_total_trades_{pair_key}_{window_key}": flow_metrics.total_trades,
            f"order_flow_avg_trade_size_{pair_key}_{window_key}": flow_metrics.avg_trade_size,
            f"order_flow_large_trade_count_{pair_key}_{window_key}": flow_metrics.large_trade_count,
            f"order_flow_vwap_{pair_key}_{window_key}": flow_metrics.vwap,
            f"order_flow_strength_{pair_key}_{window_key}": flow_metrics.flow_strength,
            f"order_flow_tick_direction_{pair_key}_{window_key}": flow_metrics.tick_direction_sum,
            f"order_flow_aggressive_ratio_{pair_key}_{window_key}": flow_metrics.aggressive_trade_ratio,
        }

        await self.metrics.emit_metrics(metrics)

    def get_flow_signal(
        self, pair: str, window_seconds: int = 60
    ) -> Optional[Tuple[FlowSignal, float]]:
        """Get current flow signal for a pair and window"""
        metrics = self.flow_metrics.get(pair, {}).get(window_seconds)
        if metrics:
            return metrics.flow_signal, metrics.flow_strength
        return None

    def get_flow_metrics(self, pair: str, window_seconds: int = 60) -> Optional[FlowMetrics]:
        """Get complete flow metrics for a pair and window"""
        return self.flow_metrics.get(pair, {}).get(window_seconds)

    def get_all_flow_signals(self, pair: str) -> Dict[int, Tuple[FlowSignal, float]]:
        """Get flow signals for all configured windows"""
        signals: Dict[int, Tuple[FlowSignal, float]] = {}
        pair_metrics = self.flow_metrics.get(pair, {})
        for window_seconds, metrics in pair_metrics.items():
            signals[window_seconds] = (metrics.flow_signal, metrics.flow_strength)
        return signals

    def detect_block_trades(self, pair: str, lookback_seconds: int = 300) -> List[TradeEvent]:
        """Detect recent block trades (large institutional trades)"""
        trades = list(self.trades.get(pair, []))
        if not trades:
            return []

        cutoff = time.time() - float(lookback_seconds)
        recent_trades = [t for t in trades if t.timestamp >= cutoff]
        block_trades = [t for t in recent_trades if t.volume >= self.config.block_trade_btc]
        return sorted(block_trades, key=lambda x: x.timestamp, reverse=True)

    def detect_whale_activity(self, pair: str, lookback_seconds: int = 600) -> Dict[str, Any]:
        """Detect whale trading activity"""
        trades = list(self.trades.get(pair, []))
        if not trades:
            return {}

        cutoff = time.time() - float(lookback_seconds)
        recent_trades = [t for t in trades if t.timestamp >= cutoff]
        whale_trades = [t for t in recent_trades if t.volume >= self.config.whale_trade_btc]
        if not whale_trades:
            return {}

        total_whale_volume = float(sum(t.volume for t in whale_trades))
        whale_buy_volume = float(
            sum(t.volume for t in whale_trades if t.direction == TradeDirection.BUY)
        )
        whale_sell_volume = float(
            sum(t.volume for t in whale_trades if t.direction == TradeDirection.SELL)
        )
        denom = (whale_buy_volume + whale_sell_volume) or 1e-8
        whale_imbalance = (whale_buy_volume - whale_sell_volume) / denom

        return {
            "whale_trades": whale_trades,
            "total_whale_volume": total_whale_volume,
            "whale_buy_volume": whale_buy_volume,
            "whale_sell_volume": whale_sell_volume,
            "whale_imbalance": whale_imbalance,
            "whale_trade_count": len(whale_trades),
        }

    def get_volume_profile(
        self, pair: str, window_seconds: int = 300, price_buckets: int = 20
    ) -> Dict[float, float]:
        """Get volume profile (volume at price levels)"""
        trades = list(self.trades.get(pair, []))
        if not trades:
            return {}

        cutoff = time.time() - float(window_seconds)
        recent_trades = [t for t in trades if t.timestamp >= cutoff]
        if not recent_trades:
            return {}

        prices = [t.price for t in recent_trades]
        min_price, max_price = min(prices), max(prices)

        # Single-price edge case
        if min_price == max_price:
            return {float(min_price): float(sum(t.volume for t in recent_trades))}

        # Guard bucket sizing
        price_buckets = max(1, int(price_buckets))
        bucket_size = (max_price - min_price) / float(price_buckets)
        if bucket_size <= 0:
            return {float(min_price): float(sum(t.volume for t in recent_trades))}

        volume_profile: Dict[float, float] = defaultdict(float)
        for trade in recent_trades:
            idx = int((trade.price - min_price) / bucket_size)
            if idx >= price_buckets:
                idx = price_buckets - 1
            bucket_price = min_price + idx * bucket_size
            volume_profile[float(bucket_price)] += float(trade.volume)

        return dict(volume_profile)

    def is_flow_favorable_for_scalping(self, pair: str) -> Tuple[bool, str]:
        """
        Determine if current order flow is favorable for scalping.

        Returns:
            (is_favorable, reason)
        """
        short_flow = self.get_flow_metrics(pair, 30)  # 30s
        medium_flow = self.get_flow_metrics(pair, 60)  # 1min

        if not short_flow or not medium_flow:
            return False, "Insufficient flow data"

        # Strong momentum across timeframes
        if short_flow.flow_signal in {FlowSignal.STRONG_BUY, FlowSignal.STRONG_SELL}:
            if medium_flow.flow_signal in {FlowSignal.STRONG_BUY, FlowSignal.STRONG_SELL}:
                return True, f"Strong directional flow: {short_flow.flow_signal.value}"
            # short-term spike without medium support
            return False, "Conflicting flow signals across timeframes"

        # Excessive short-term volatility (bps threshold)
        if abs(short_flow.price_change_bps) > 50.0:
            return False, f"Excessive short-term volatility: {short_flow.price_change_bps:.1f} bps"

        # Trade activity sufficiency
        if short_flow.total_trades < 5:
            return False, "Insufficient trade activity"

        # Balanced flow for mean reversion
        if abs(short_flow.volume_imbalance) < 0.3 and abs(medium_flow.volume_imbalance) < 0.3:
            return True, "Balanced flow suitable for mean reversion"

        # Consistent direction with adequate strength
        if (
            short_flow.flow_signal == medium_flow.flow_signal
            and short_flow.flow_strength > self.config.flow_strength_threshold
        ):
            return True, f"Consistent {short_flow.flow_signal.value} flow"

        return False, "No clear scalping opportunity in flow"

    def get_performance_stats(self) -> Dict[str, float]:
        """Get processing performance statistics (ms-based percentiles + wall-clock TPS)"""
        if not self._proc_times_ms:
            return {}

        times = np.array(self._proc_times_ms, dtype=float)
        # Wall-time throughput over the capture window
        if len(self._proc_timestamps) >= 2:
            dt = max(1e-6, self._proc_timestamps[-1] - self._proc_timestamps[0])
            tps = len(self._proc_timestamps) / dt
        else:
            tps = 0.0

        return {
            "avg_processing_time_ms": float(np.mean(times)),
            "p95_processing_time_ms": float(np.percentile(times, 95)),
            "p99_processing_time_ms": float(np.percentile(times, 99)),
            "max_processing_time_ms": float(np.max(times)),
            "total_trades_processed": float(len(times)),
            "trades_per_second": float(tps),
        }

    async def cleanup(self) -> None:
        """Cleanup resources"""
        self.trades.clear()
        self.flow_metrics.clear()
        self.last_prices.clear()
        self._proc_times_ms.clear()
        self._proc_timestamps.clear()
        self.logger.info("Order flow analyzer cleaned up")


# Factory function for Kraken optimization
def create_kraken_order_flow_analyzer() -> OrderFlowAnalyzer:
    """Create a Kraken-optimized order flow analyzer"""
    config = OrderFlowConfig(
        large_trade_btc=0.5,  # 0.5 BTC for Kraken
        block_trade_btc=2.0,  # 2 BTC institutional threshold
        whale_trade_btc=10.0,  # 10 BTC whale threshold
        tick_size_usd=0.1,  # Kraken BTC/USD tick size
        strong_imbalance_threshold=0.7,
        weak_imbalance_threshold=0.3,
        flow_strength_threshold=0.6,
        analysis_windows=[10, 30, 60, 300],  # 10s, 30s, 1min, 5min
    )
    return OrderFlowAnalyzer(config)
