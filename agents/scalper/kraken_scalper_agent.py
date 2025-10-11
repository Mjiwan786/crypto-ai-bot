# agents/scalper/kraken_scalper_agent.py
"""
Main Kraken Scalper Agent - Orchestrates all scalping components
Integrates with existing crypto-ai-bot architecture
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agents.scalper.analysis.liquidity import (
    LiquiditySignal,
    OrderBookSnapshot,
    liquidity_signal,
)
from agents.scalper.config_loader import load_scalper_config
from agents.scalper.execution.kraken_gateway import KrakenGateway
from agents.scalper.execution.order_optimizer import OrderOptimizer
from agents.scalper.execution.position_manager import PositionManager
from agents.scalper.infra.redis_bus import RedisBus
from agents.scalper.infra.state_manager import StateManager
from agents.scalper.monitoring.performance import PerformanceMonitor

# from agents.scalper.risk.limits import LimitsManager  # noqa: F401 (kept for future use)
from agents.scalper.protections.circuit_breakers import CircuitBreakerManager
from agents.scalper.risk.risk_manager import RiskManager

# Internal imports from existing architecture
from base.trading_agent import TradingAgent
from mcp.schemas import (
    MetricsTick,
    OrderIntent,
    OrderSide,
    OrderType,
    TimeInForce,
)
from utils.logger import get_logger

# constants
_BPS_TO_PCT = 1.0 / 10_000.0  # 1 bps = 1/10000


class ScalperState(str, Enum):
    INITIALIZING = "initializing"
    ACTIVE = "active"
    PAUSED = "paused"
    CIRCUIT_BREAKER = "circuit_breaker"
    SHUTTING_DOWN = "shutting_down"
    ERROR = "error"


class ScalperSignal(BaseModel):
    """Internal scalper signal with enriched context"""

    symbol: str
    side: str  # 'buy' or 'sell' (converted to OrderSide when building OrderIntent)
    confidence: float
    liquidity_score: float
    spread_bps: float
    book_imbalance: float
    expected_profit_bps: float
    risk_score: float
    timestamp: float
    features: Dict[str, float] = Field(default_factory=dict)


@dataclass
class ScalperMetrics:
    """Real-time scalper performance metrics"""

    trades_today: int = 0
    trades_last_hour: int = 0
    trades_last_minute: int = 0
    win_rate_1h: float = 0.0
    avg_profit_bps: float = 0.0
    avg_hold_time_seconds: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    avg_latency_ms: float = 0.0
    last_trade_time: Optional[float] = None
    active_positions: int = 0

    # Circuit breaker metrics
    consecutive_losses: int = 0
    api_errors_last_minute: int = 0
    spread_violations: int = 0


@dataclass
class Features:
    """Normalized access to liquidity features (supports dict input)."""

    depth_bid_notional: float = 0.0
    depth_ask_notional: float = 0.0
    tight_spread_score: float = 0.0
    depth_balance_score: float = 0.5
    spread_bps: float = 0.0
    imbalance_score: float = 0.5
    best_bid: float = 0.0
    best_ask: float = 0.0

    @classmethod
    def from_mapping(cls, m: Any) -> "Features":
        if m is None:
            return cls()
        if isinstance(m, cls):
            return m

        def _get(k, default=0.0):
            try:
                return getattr(m, k)
            except Exception:
                return m.get(k, default) if isinstance(m, dict) else default

        return cls(
            depth_bid_notional=float(_get("depth_bid_notional", 0.0)),
            depth_ask_notional=float(_get("depth_ask_notional", 0.0)),
            tight_spread_score=float(_get("tight_spread_score", 0.0)),
            depth_balance_score=float(_get("depth_balance_score", 0.5)),
            spread_bps=float(_get("spread_bps", 0.0)),
            imbalance_score=float(_get("imbalance_score", 0.5)),
            best_bid=float(_get("best_bid", 0.0)),
            best_ask=float(_get("best_ask", 0.0)),
        )


class KrakenScalperAgent(TradingAgent):
    """
    High-frequency scalping agent for Kraken exchange

    Integrates all scalping components into a cohesive trading system:
    - Market microstructure analysis
    - Signal generation and filtering
    - Position and risk management
    - Order execution optimization
    - Performance monitoring
    """

    def __init__(self, config_path: str = "agents/scalper/config/settings.yaml"):
        super().__init__("kraken_scalper")

        # Store config path for lazy loading
        self.config_path = config_path
        self.config = None  # Load lazily in startup()
        self.logger = get_logger(f"scalper.{self.agent_id}")

        # Agent state
        self.state = ScalperState.INITIALIZING
        self.metrics = ScalperMetrics()
        self.last_order_book: Optional[OrderBookSnapshot] = None
        self.active_signals: Dict[str, ScalperSignal] = {}
        self.pending_orders: Dict[str, dict] = {}

        # Core components - initialize in startup
        self.position_manager: Optional[PositionManager] = None
        self.risk_manager: Optional[RiskManager] = None
        self.order_optimizer: Optional[OrderOptimizer] = None
        self.kraken_gateway: Optional[KrakenGateway] = None
        self.circuit_breakers: Optional[CircuitBreakerManager] = None
        self.performance_tracker: Optional[PerformanceMonitor] = None
        self.state_manager: Optional[StateManager] = None
        self.redis_bus: Optional[RedisBus] = None

        # Trading parameters (initialized with defaults, updated in startup)
        self.target_bps = 10.0
        self.stop_loss_bps = 20.0
        self.max_spread_bps = 50.0
        self.min_liquidity_score = 0.7
        self.max_hold_seconds = 30

        # Rate limiting (defaults)
        self.max_trades_per_minute = 5
        self.max_trades_per_hour = 100
        self.cooldown_after_loss = 60

        # Track trade timing for rate limiting
        self.trade_timestamps: deque[float] = deque()
        self.last_loss_time: Optional[float] = None

        self.logger.info(f"Kraken Scalper Agent initialized (config will be loaded on startup)")

    async def startup(self) -> bool:
        """Initialize all components and connections"""
        try:
            self.logger.info("Starting Kraken Scalper Agent...")

            # Load configuration
            self.config = load_scalper_config(self.config_path)

            # Update trading parameters from loaded config
            scalping_cfg = getattr(self.config, "scalping", {})
            self.target_bps = getattr(scalping_cfg, "target_bps", self.target_bps)
            self.stop_loss_bps = getattr(scalping_cfg, "stop_loss_bps", self.stop_loss_bps)
            self.max_spread_bps = getattr(scalping_cfg, "max_spread_bps", self.max_spread_bps)
            self.min_liquidity_score = getattr(scalping_cfg, "min_liquidity_score", self.min_liquidity_score)
            self.max_hold_seconds = getattr(scalping_cfg, "max_hold_seconds", self.max_hold_seconds)
            self.max_trades_per_minute = getattr(scalping_cfg, "max_trades_per_minute", self.max_trades_per_minute)
            self.max_trades_per_hour = getattr(scalping_cfg, "max_trades_per_hour", self.max_trades_per_hour)
            self.cooldown_after_loss = getattr(scalping_cfg, "cooldown_after_loss_seconds", self.cooldown_after_loss)

            self.logger.info(f"Configuration loaded from {self.config_path}")

            # Initialize Redis message bus
            self.redis_bus = RedisBus(self.config.redis)
            await self.redis_bus.initialize()

            # Initialize state manager
            self.state_manager = StateManager(
                agent_id=self.agent_id, redis_client=self.redis_bus.client
            )
            await self.state_manager.initialize()

            # Initialize Kraken gateway
            self.kraken_gateway = KrakenGateway(
                api_key=self.config.kraken.api_key,
                api_secret=self.config.kraken.api_secret,
                sandbox=self.config.kraken.sandbox,
            )
            await self.kraken_gateway.initialize()

            # Initialize core trading components
            self.position_manager = PositionManager(
                gateway=self.kraken_gateway, config=self.config.position_sizing
            )

            self.risk_manager = RiskManager(
                config=self.config.risk_controls, position_manager=self.position_manager
            )

            self.order_optimizer = OrderOptimizer(
                gateway=self.kraken_gateway, config=self.config.execution
            )

            # Initialize circuit breakers
            self.circuit_breakers = CircuitBreakerManager(self.config.circuit_breakers)

            # Initialize performance tracking
            self.performance_tracker = PerformanceMonitor(
                agent_id=self.agent_id, redis_client=self.redis_bus.client
            )

            # Subscribe to market data streams
            await self._setup_subscriptions()

            # Load any persistent state
            await self._restore_state()

            self.state = ScalperState.ACTIVE
            self.logger.info("Kraken Scalper Agent startup complete")

            return True

        except Exception:
            self.logger.exception("Failed to start scalper agent")
            self.state = ScalperState.ERROR
            return False

    async def _setup_subscriptions(self):
        """Setup Redis stream subscriptions for market data"""
        if not self.redis_bus:
            self.logger.error("RedisBus not initialized; cannot subscribe")
            return

        # Subscribe to Kraken order book updates
        await self.redis_bus.subscribe_stream(
            "kraken:book",
            self._handle_order_book_update,
            consumer_group="scalper_book",
            consumer_name=f"scalper_{self.agent_id}",
        )

        # Subscribe to trade data for market context
        await self.redis_bus.subscribe_stream(
            "kraken:trade",
            self._handle_trade_update,
            consumer_group="scalper_trade",
            consumer_name=f"scalper_{self.agent_id}",
        )

        # Subscribe to spread updates for liquidity monitoring
        await self.redis_bus.subscribe_stream(
            "kraken:spread",
            self._handle_spread_update,
            consumer_group="scalper_spread",
            consumer_name=f"scalper_{self.agent_id}",
        )

    async def _handle_order_book_update(self, data: dict):
        """Process incoming order book updates - main entry point"""
        if self.state != ScalperState.ACTIVE:
            return

        try:
            # Parse order book data
            order_book = self._parse_order_book(data)
            if not order_book:
                return

            self.last_order_book = order_book

            # Generate liquidity signal
            liq_sig: LiquiditySignal = liquidity_signal(order_book, k=5)

            # Check circuit breakers first
            if await self._check_circuit_breakers(liq_sig):
                return

            # Generate trading signal
            scalper_sig = await self._generate_scalper_signal(order_book, liq_sig)

            if scalper_sig:
                # Process the signal
                await self._process_scalper_signal(scalper_sig)

        except Exception:
            self.logger.exception("Error handling order book update")
            self.metrics.api_errors_last_minute += 1

    async def _generate_scalper_signal(
        self, order_book: OrderBookSnapshot, liq_sig: LiquiditySignal
    ) -> Optional[ScalperSignal]:
        """Generate actionable scalping signal from market data"""

        symbol = getattr(order_book, "symbol", None) or "UNKNOWN"

        # Normalize features access
        f = Features.from_mapping(getattr(liq_sig, "features", {}) or {})

        # Check minimum requirements
        if (
            f.spread_bps > self.max_spread_bps
            or getattr(liq_sig, "score_overall", 0.0) < self.min_liquidity_score
        ):
            self.logger.debug("Signal dropped due to spread/liquidity thresholds")
            return None

        # Determine signal direction based on book imbalance
        side = None
        confidence = 0.0
        if f.imbalance_score > 0.65:  # Strong buy pressure
            side = "buy"
            confidence = min(f.imbalance_score + 0.2, 1.0)
        elif f.imbalance_score < 0.35:  # Strong sell pressure
            side = "sell"
            confidence = min((1.0 - f.imbalance_score) + 0.2, 1.0)
        else:
            return None  # Not enough directional bias

        # Calculate expected profit accounting for spread
        expected_profit_bps = self.target_bps - (f.spread_bps / 2.0)
        if expected_profit_bps < 3:  # Minimum viable profit after costs
            self.logger.debug("Expected profit below minimum after spread costs")
            return None

        # Risk assessment
        risk_score = self._calculate_risk_score(f)
        if risk_score > 0.7:  # Too risky
            self.logger.debug("Signal too risky, dropping")
            return None

        return ScalperSignal(
            symbol=symbol,
            side=side,
            confidence=float(confidence),
            liquidity_score=float(getattr(liq_sig, "score_overall", 0.0)),
            spread_bps=float(f.spread_bps),
            book_imbalance=float(f.imbalance_score),
            expected_profit_bps=float(expected_profit_bps),
            risk_score=float(risk_score),
            timestamp=time.time(),
            features={
                "depth_bid": f.depth_bid_notional,
                "depth_ask": f.depth_ask_notional,
                "tight_spread_score": f.tight_spread_score,
                "depth_balance_score": f.depth_balance_score,
                "best_bid": f.best_bid,
                "best_ask": f.best_ask,
                "spread_bps": f.spread_bps,
                "imbalance_score": f.imbalance_score,
            },
        )

    def _calculate_risk_score(self, f: Features) -> float:
        """Calculate risk score based on market microstructure"""
        risk = 0.0

        # Spread risk - wider spreads = higher risk
        spread_risk = min(f.spread_bps / 10.0, 1.0) * 0.3
        risk += spread_risk

        # Depth risk - shallow book = higher risk
        min_depth = min(f.depth_bid_notional or 0.0, f.depth_ask_notional or 0.0)
        depth_risk = max(0.0, 1.0 - (min_depth / 10_000.0)) * 0.4  # $10k baseline
        risk += depth_risk

        # Balance risk - imbalanced book = higher risk of reversal
        balance_risk = (1.0 - (f.depth_balance_score or 0.5)) * 0.3
        risk += balance_risk

        return float(risk)

    async def _process_scalper_signal(self, signal: ScalperSignal):
        """Process validated scalper signal"""

        # Check rate limiting
        if not await self._check_rate_limits():
            self.logger.debug("Rate limits reached — skipping signal")
            return

        # Check cooldown after losses
        if self.last_loss_time and (time.time() - self.last_loss_time) < self.cooldown_after_loss:
            self.logger.debug("In cooldown after loss — skipping")
            return

        # Risk management check
        if not self.risk_manager:
            self.logger.error("RiskManager not initialized; cannot open position")
            return

        try:
            allowed = await self.risk_manager.can_open_position(signal.symbol, signal.side)
        except Exception:
            self.logger.exception("RiskManager error evaluating position")
            return

        if not allowed:
            self.logger.debug(f"Risk manager rejected position for {signal.symbol}")
            return

        # Generate order intent
        order_intent = await self._create_order_intent(signal)
        if not order_intent:
            self.logger.debug("Order intent could not be created for signal")
            return

        # Execute order in background (non-blocking)
        asyncio.create_task(self._execute_order(order_intent, signal))

        # Store active signal for monitoring
        self.active_signals[signal.symbol] = signal

    async def _create_order_intent(self, signal: ScalperSignal) -> Optional[OrderIntent]:
        """Create order intent from scalper signal"""
        if not self.position_manager:
            self.logger.error("PositionManager not initialized")
            return None

        try:
            position_size_usd = await self.position_manager.calculate_position_size(
                signal.symbol,
                signal.risk_score,
                getattr(self.config.position_sizing, "base_size_usd", 100.0),
            )
        except Exception:
            self.logger.exception("Position size calc failed")
            return None

        if position_size_usd < getattr(self.config.position_sizing, "min_size_usd", 1.0):
            return None

        if not self.last_order_book:
            self.logger.debug("No last order book available to price order")
            return None

        f = Features.from_mapping(signal.features)

        best_bid = f.best_bid or self._best_bid_from_orderbook(self.last_order_book)
        best_ask = f.best_ask or self._best_ask_from_orderbook(self.last_order_book)
        if best_bid <= 0 or best_ask <= 0:
            self.logger.debug("Invalid best bid/ask; skipping order intent")
            return None

        # Calculate price using bps spread fraction of mid-sensitivity
        if signal.side.lower() == "buy":
            # Slightly above best bid to prefer maker fills without crossing
            price = best_bid + (f.spread_bps * _BPS_TO_PCT * best_bid * 0.3)
            side_enum = OrderSide.BUY
        else:
            price = best_ask - (f.spread_bps * _BPS_TO_PCT * best_ask * 0.3)
            side_enum = OrderSide.SELL

        if price <= 0:
            self.logger.debug("Computed non-positive price; skipping")
            return None

        # Build OrderIntent (schemas.py validators enforce Kraken rules)
        intent = OrderIntent(
            symbol=signal.symbol,  # schemas.py enforces "BASE/QUOTE"
            side=side_enum,  # enum required
            order_type=OrderType.LIMIT,  # LIMIT for maker/post-only
            price=price,  # required for LIMIT
            size_quote_usd=position_size_usd,  # >= 1.0 enforced by schema
            post_only=True,  # only valid for LIMIT per schema
            tif=TimeInForce.GTC,  # Kraken-safe (IOC/FOK not allowed)
            metadata={
                "strategy": "kraken_scalp",
                "signal_id": f"scalp_{int(signal.timestamp)}",
                "expected_profit_bps": signal.expected_profit_bps,
                "stop_loss_bps": self.stop_loss_bps,
                "max_hold_seconds": self.max_hold_seconds,
                "exchange": "kraken",
            },
        )
        return intent

    async def _execute_order(self, order_intent: OrderIntent, signal: ScalperSignal):
        """Execute order through optimized gateway"""
        if not self.order_optimizer or not self.kraken_gateway:
            self.logger.error("OrderOptimizer or KrakenGateway not available")
            return

        try:
            optimized_order = await self.order_optimizer.optimize_order(order_intent)
            order_result = await self.kraken_gateway.submit_order(optimized_order)

            if order_result.get("success"):
                order_id = order_result.get("order_id")
                self.pending_orders[order_id] = {
                    "signal": signal,
                    "order_intent": order_intent,
                    "submit_time": time.time(),
                    "status": "pending",
                    # fill_price & position_size will be added on fill
                }
                self._update_trade_metrics()

                # Monitor in background
                asyncio.create_task(self._monitor_position(order_id, signal))

                self.logger.info(f"Scalp order submitted: {order_id} for {signal.symbol}")
            else:
                self.logger.warning(f"Order submission failed: {order_result}")

        except Exception:
            self.logger.exception("Error executing order")
            self.metrics.api_errors_last_minute += 1

    async def _monitor_position(self, order_id: str, signal: ScalperSignal):
        """Monitor position for exit conditions"""
        if not self.kraken_gateway:
            self.logger.error("KrakenGateway missing — cannot monitor position")
            return

        start_time = time.time()
        try:
            while order_id in self.pending_orders and self.state == ScalperState.ACTIVE:
                try:
                    order_status = await self.kraken_gateway.get_order_status(order_id)
                except Exception:
                    self.logger.exception("Failed fetching order status from gateway")
                    await asyncio.sleep(1)
                    continue

                if order_status.get("filled"):
                    # store fill info
                    fill_price = order_status.get("fill_price") or order_status.get(
                        "avg_fill_price"
                    )
                    position_size = order_status.get("filled_size") or order_status.get("size")
                    self.pending_orders[order_id].update(
                        {
                            "status": "filled",
                            "fill_price": fill_price,
                            "position_size": position_size,
                        }
                    )
                    await self._setup_exit_orders(order_id, signal)
                    break

                if order_status.get("cancelled") or order_status.get("rejected"):
                    self.pending_orders.pop(order_id, None)
                    break

                # Check time-based exit
                if time.time() - start_time > self.max_hold_seconds:
                    await self._cancel_order(order_id, "time_exit")
                    break

                # Check if signal still valid
                if not await self._is_signal_valid(signal):
                    await self._cancel_order(order_id, "signal_invalid")
                    break

                # Wait before next check
                await asyncio.sleep(1)

        except Exception:
            self.logger.exception(f"Error monitoring position {order_id}")
        finally:
            # cleanup if still present
            self.pending_orders.pop(order_id, None)

    async def _setup_exit_orders(self, entry_order_id: str, signal: ScalperSignal):
        """Setup profit target and stop loss orders"""
        try:
            order_info = self.pending_orders.get(entry_order_id)
            if not order_info:
                return

            fill_price = order_info.get("fill_price")
            position_size = order_info.get("position_size")

            if fill_price is None or position_size is None:
                self.logger.warning("Missing fill_price/position_size — cannot setup exits")
                return

            if signal.side.lower() == "buy":
                profit_price = fill_price * (1.0 + (self.target_bps * _BPS_TO_PCT))
                stop_price = fill_price * (1.0 - (self.stop_loss_bps * _BPS_TO_PCT))
                exit_side = "sell"
            else:
                profit_price = fill_price * (1.0 - (self.target_bps * _BPS_TO_PCT))
                stop_price = fill_price * (1.0 + (self.stop_loss_bps * _BPS_TO_PCT))
                exit_side = "buy"

            # Profit target (reduce-only limit)
            profit_order = await self.kraken_gateway.submit_order(
                {
                    "symbol": signal.symbol,
                    "side": exit_side,
                    "type": "limit",
                    "price": profit_price,
                    "size": position_size,
                    "post_only": True,
                    "reduce_only": True,
                }
            )

            # Stop loss
            stop_order = await self.kraken_gateway.submit_order(
                {
                    "symbol": signal.symbol,
                    "side": exit_side,
                    "type": "stop_loss",
                    "stop_price": stop_price,
                    "size": position_size,
                    "reduce_only": True,
                }
            )

            self.logger.info(
                f"Exit orders setup for {entry_order_id}: "
                f"profit={profit_order.get('order_id')}, stop={stop_order.get('order_id')}"
            )

        except Exception:
            self.logger.exception(f"Failed to setup exit orders for {entry_order_id}")

    async def _check_rate_limits(self) -> bool:
        """Check if we can place a new trade based on rate limits"""
        current_time = time.time()

        # remove > 1 hour old timestamps
        while self.trade_timestamps and (current_time - self.trade_timestamps[0]) > 3600:
            self.trade_timestamps.popleft()

        # per-minute limit
        recent_minute = sum(1 for ts in self.trade_timestamps if (current_time - ts) < 60)
        if recent_minute >= self.max_trades_per_minute:
            return False

        # per-hour limit
        if len(self.trade_timestamps) >= self.max_trades_per_hour:
            return False

        return True

    async def _check_circuit_breakers(self, liq_sig: LiquiditySignal) -> bool:
        """Check if any circuit breakers should halt trading"""
        if not self.circuit_breakers:
            self.logger.debug("CircuitBreakerManager not available")
            return False

        f = Features.from_mapping(getattr(liq_sig, "features", {}) or {})

        # Spread circuit breaker
        if f.spread_bps > getattr(
            self.config.circuit_breakers, "max_spread_bps", self.max_spread_bps
        ):
            await self.circuit_breakers.trigger(
                "spread_too_wide",
                {
                    "spread_bps": f.spread_bps,
                    "max_allowed": getattr(
                        self.config.circuit_breakers, "max_spread_bps", self.max_spread_bps
                    ),
                },
            )
            return True

        # Liquidity circuit breaker
        if getattr(liq_sig, "score_overall", 0.0) < 0.3:
            await self.circuit_breakers.trigger(
                "low_liquidity",
                {"liquidity_score": getattr(liq_sig, "score_overall", 0.0)},
            )
            return True

        # Consecutive losses circuit breaker
        if self.metrics.consecutive_losses >= getattr(
            self.config.circuit_breakers, "consecutive_losses_threshold", 3
        ):
            await self.circuit_breakers.trigger(
                "consecutive_losses", {"losses": self.metrics.consecutive_losses}
            )
            return True

        return False

    def _update_trade_metrics(self):
        """Update internal trading metrics"""
        now = time.time()
        self.trade_timestamps.append(now)
        self.metrics.trades_today += 1
        self.metrics.last_trade_time = now

        hour_ago = now - 3600
        minute_ago = now - 60

        self.metrics.trades_last_hour = sum(1 for ts in self.trade_timestamps if ts > hour_ago)
        self.metrics.trades_last_minute = sum(1 for ts in self.trade_timestamps if ts > minute_ago)

    async def get_health_status(self) -> dict:
        """Return agent health status"""
        cb_status = {}
        try:
            cb_status = await self.circuit_breakers.get_status() if self.circuit_breakers else {}
        except Exception:
            self.logger.exception("Failed fetching circuit breaker status")

        return {
            "state": self.state.value,
            "active_positions": self.metrics.active_positions,
            "trades_today": self.metrics.trades_today,
            "win_rate_1h": self.metrics.win_rate_1h,
            "pnl": self.metrics.total_pnl,
            "max_drawdown": self.metrics.max_drawdown,
            "avg_latency_ms": self.metrics.avg_latency_ms,
            "circuit_breakers": cb_status,
            "last_update": time.time(),
        }

    async def get_metrics(self) -> MetricsTick:
        """Return performance metrics in MCP format"""
        return MetricsTick(
            pnl={
                "realized": self.metrics.total_pnl,
                "unrealized": 0.0,  # Calculate from open positions if you track them
                "fees": 0.0,  # Track separately
            },
            slippage_bps_p50=2.5,  # Track from executions
            latency_ms_p95=self.metrics.avg_latency_ms,
            win_rate_1h=self.metrics.win_rate_1h,
            drawdown_daily=self.metrics.max_drawdown,
            errors_rate=(self.metrics.api_errors_last_minute / max(60.0, 1.0)),
        )

    async def pause(self):
        """Pause trading activity"""
        self.state = ScalperState.PAUSED
        self.logger.info("Scalper agent paused")

    async def resume(self):
        """Resume trading activity"""
        if self.state == ScalperState.PAUSED:
            self.state = ScalperState.ACTIVE
            self.logger.info("Scalper agent resumed")

    async def shutdown(self):
        """Graceful shutdown"""
        self.logger.info("Shutting down Kraken Scalper Agent...")
        self.state = ScalperState.SHUTTING_DOWN

        # Cancel all pending orders
        for order_id in list(self.pending_orders.keys()):
            try:
                await self._cancel_order(order_id, "shutdown")
            except Exception:
                self.logger.exception(f"Error cancelling order {order_id}")

        # Save state
        if self.state_manager:
            try:
                await self.state_manager.save_state(
                    {
                        "metrics": self.metrics.__dict__,
                        "active_signals": {
                            k: v.model_dump() for k, v in self.active_signals.items()
                        },
                    }
                )
            except Exception:
                self.logger.exception("Failed to save state during shutdown")

        # Cleanup components
        if self.redis_bus:
            await self.redis_bus.close()
        if self.kraken_gateway:
            await self.kraken_gateway.close()

        self.logger.info("Scalper agent shutdown complete")

    # Helper methods for data parsing and validation
    def _parse_order_book(self, data: dict) -> Optional[OrderBookSnapshot]:
        """Parse order book data from Redis stream"""
        try:
            # Expected formats supported:
            # {'timestamp': <ms>, 'symbol': 'BTC/USD', 'bids': [[p, s], ...], 'asks': [[p, s], ...]}
            ts_ms = int(data.get("timestamp", int(time.time() * 1000)))
            symbol = data.get("symbol") or data.get("pair") or "UNKNOWN"

            raw_bids = data.get("bids", []) or []
            raw_asks = data.get("asks", []) or []

            bids = [(float(p), float(s)) for p, s in raw_bids] if raw_bids else []
            asks = [(float(p), float(s)) for p, s in raw_asks] if raw_asks else []

            return OrderBookSnapshot(ts_ms=ts_ms, symbol=symbol, bids=bids, asks=asks)
        except Exception:
            self.logger.exception("Failed to parse order book")
            return None

    async def _handle_trade_update(self, data: dict):
        """Handle trade data for market context"""
        # Extend: volatility, trade flow, etc.
        pass

    async def _handle_spread_update(self, data: dict):
        """Handle spread updates"""
        # Extend: maintain rolling spread metrics if needed
        pass

    async def _is_signal_valid(self, signal: ScalperSignal) -> bool:
        """Check if signal is still valid"""
        return (time.time() - signal.timestamp) < 30  # 30 second validity

    async def _cancel_order(self, order_id: str, reason: str):
        """Cancel order and clean up"""
        try:
            if self.kraken_gateway:
                await self.kraken_gateway.cancel_order(order_id)
            self.pending_orders.pop(order_id, None)
            self.logger.info(f"Cancelled order {order_id}: {reason}")
        except Exception:
            self.logger.exception(f"Failed to cancel order {order_id}")

    async def _restore_state(self):
        """Restore agent state from persistence"""
        if not self.state_manager:
            return
        try:
            saved_state = await self.state_manager.load_state()
            if saved_state:
                # Restore metrics
                metrics = saved_state.get("metrics", {})
                for k, v in metrics.items():
                    if hasattr(self.metrics, k):
                        setattr(self.metrics, k, v)
                self.logger.info("Restored agent state from persistence")
        except Exception:
            self.logger.exception("Failed to restore state")

    # helpers to compute best bid/ask from order book if needed
    def _best_bid_from_orderbook(self, ob: OrderBookSnapshot) -> float:
        if not ob or not getattr(ob, "bids", None):
            return 0.0
        return max((p for p, _ in ob.bids), default=0.0)

    def _best_ask_from_orderbook(self, ob: OrderBookSnapshot) -> float:
        if not ob or not getattr(ob, "asks", None):
            return 0.0
        return min((p for p, _ in ob.asks), default=0.0)
