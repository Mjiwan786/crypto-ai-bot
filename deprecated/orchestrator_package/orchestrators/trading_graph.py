"""
LangGraph-based Trading Orchestrator

DAG Flow:
    fetch_context_node
           ↓
    scan_market_node
           ↓
    analyze_signals_node
           ↓
    risk_and_compliance_node
           ↓
    strategy_select_node ──→ (conditional) ──→ execute_node
           ↓                                       ↓
           └──────────────────────────────────→ monitor_node
                                                   ↓
                                              learn_node

Runs one complete pass of the trading loop with checkpointing,
observability, and graceful failure handling.
"""

from __future__ import annotations

import asyncio
import os
import uuid
import time
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from pydantic import Field

# ---- LangGraph typing-safe imports ----
# We import real types only for static type checking. At runtime, we
# fall back to string constants and Any so the module works even when
# LangGraph isn't installed.
if TYPE_CHECKING:
    from langgraph.graph import StateGraph, START, END
    from langgraph.graph.state import CompiledStateGraph as _CompiledStateGraph
    CompiledGraphT = _CompiledStateGraph
else:
    StateGraph = None  # type: ignore
    START = "start"    # type: ignore
    END = "end"        # type: ignore
    from typing import Any as CompiledGraphT  # runtime fallback

# ---- Config imports with fallback ----
try:
    from config.config_loader import get_config
except Exception:  # pragma: no cover
    try:
        from ..config.config_loader import get_config  # type: ignore
    except Exception:
        from orchestrator_package.config.config_loader import get_config  # type: ignore

# ---- Schema imports with fallback ----
try:
    from mcp.schemas import VersionedBaseModel, Signal, OrderIntent, MetricsTick, OrderSide
except Exception:  # pragma: no cover
    try:
        from ..mcp.schemas import VersionedBaseModel, Signal, OrderIntent, MetricsTick, OrderSide  # type: ignore
    except Exception:
        from orchestrator_package.mcp.schemas import VersionedBaseModel, Signal, OrderIntent, MetricsTick, OrderSide  # type: ignore

# ---- Redis/marshaling imports with fallback ----
try:
    from mcp.redis_manager import RedisManager
    from mcp.marshaling import pack_stream_fields, serialize_event, stable_hash
except Exception:  # pragma: no cover
    try:
        from ..mcp.redis_manager import RedisManager  # type: ignore
        from ..mcp.marshaling import pack_stream_fields, serialize_event, stable_hash  # type: ignore
    except Exception:
        from orchestrator_package.mcp.redis_manager import RedisManager  # type: ignore
        from orchestrator_package.mcp.marshaling import pack_stream_fields, serialize_event, stable_hash  # type: ignore

# ---- Tool imports with fallback ----
try:
    from orchestrator_package.orchestrators.tools.signal_tools import (
        process_and_publish as process_signal, FeatureFrame, SignalPlan, default_filters_from_cfg
    )
    from orchestrator_package.orchestrators.tools.exec_tools import (
        build_order_intent, send_intent, ExchangePort, NullExchange
    )
    from orchestrator_package.orchestrators.tools.risk_tools import pretrade_check, RiskContext
except Exception:  # pragma: no cover
    try:
        from .tools.signal_tools import (  # type: ignore
            process_and_publish as process_signal, FeatureFrame, SignalPlan, default_filters_from_cfg
        )
        from .tools.exec_tools import build_order_intent, send_intent, ExchangePort, NullExchange  # type: ignore
        from .tools.risk_tools import pretrade_check, RiskContext  # type: ignore
    except Exception:
        from orchestrators.tools.signal_tools import (  # type: ignore
            process_and_publish as process_signal, FeatureFrame, SignalPlan, default_filters_from_cfg
        )
        from orchestrators.tools.exec_tools import build_order_intent, send_intent, ExchangePort, NullExchange  # type: ignore
        from orchestrators.tools.risk_tools import pretrade_check, RiskContext  # type: ignore

# ---- Utils imports with fallback ----
try:
    from utils.logger import get_logger
    from utils.timer import timer
except Exception:  # pragma: no cover
    try:
        from ..utils.logger import get_logger  # type: ignore
        from ..utils.timer import timer  # type: ignore
    except Exception:
        from orchestrator_package.utils.logger import get_logger  # type: ignore
        from orchestrator_package.utils.timer import timer  # type: ignore

# ---------------------------------------------------------------------------

_config_cache = None
_redis_manager = None

logger = get_logger(__name__)

# Stream constants
STREAMS = {
    "raw_signals": "signals:raw",
    "filtered_signals": "signals:filtered",
    "order_intent": "orders:intent",
    "order_ack": "orders:ack",
    "fills": "fills",
    "metrics": "metrics:ticks",
    "checkpoints": "orchestrator:checkpoints",
}


class TradingState(VersionedBaseModel):
    """State model for the trading graph DAG"""
    schema_version: str = "1.0"
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ts_start: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str | None = None
    timeframe: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    scanned: list[str] = Field(default_factory=list)
    raw_signals: list[Signal] = Field(default_factory=list)
    filtered_signals: list[Signal] = Field(default_factory=list)
    selected: dict[str, Any] = Field(default_factory=dict)
    order_intent: OrderIntent | None = None
    order_ack: dict[str, Any] | None = None
    fills: list[dict[str, Any]] = Field(default_factory=list)
    metrics: list[MetricsTick] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def add_error(self, msg: str) -> None:
        """Add error message to state"""
        self.errors.append(f"{datetime.now(timezone.utc).isoformat()}: {msg}")
        logger.error(f"Trading state error: {msg}")

    def push_metric(self, m: MetricsTick) -> None:
        """Add metric to state"""
        self.metrics.append(m)

    def stable_id(self) -> str:
        """Generate stable hash for this state"""
        data = self.model_dump(mode="json", exclude={"ts_start"})
        return stable_hash(data)


def _get_config():
    """Lazy config loading with caching"""
    global _config_cache
    if _config_cache is None:
        _config_cache = get_config()
    return _config_cache


async def _get_redis():
    """Get Redis manager with caching"""
    global _redis_manager
    if _redis_manager is None:
        cfg = _get_config()
        _redis_manager = await RedisManager.get_or_create(url=cfg.redis.url)
    return _redis_manager


async def _checkpoint_state(state: TradingState, node_name: str) -> None:
    """Write checkpoint to Redis (best-effort)"""
    try:
        redis_mgr = await _get_redis()
        checkpoint_data = pack_stream_fields({
            "node": node_name,
            "run_id": state.run_id,
            "state_hash": state.stable_id(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "errors_count": len(state.errors),
            "signals_count": len(state.filtered_signals),
        })
        await redis_mgr.client.xadd(
            STREAMS["checkpoints"], checkpoint_data, maxlen=5000, approximate=True
        )
    except Exception as e:
        logger.warning(f"Failed to checkpoint after {node_name}: {e}")


async def _publish_metric(metric: MetricsTick) -> None:
    """Publish metric to Redis (best-effort)"""
    try:
        redis_mgr = await _get_redis()
        metric_data = pack_stream_fields(serialize_event(metric))
        await redis_mgr.client.xadd(
            STREAMS["metrics"], metric_data, maxlen=10000, approximate=True
        )
    except Exception as e:
        logger.warning(f"Failed to publish metric: {e}")


def _get_symbols_from_config(cfg) -> list[str]:
    """Get trading symbols from config or env"""
    env_symbols = os.getenv("TRADING_SYMBOLS", "")
    if env_symbols:
        return [s.strip() for s in env_symbols.split(",") if s.strip()]

    # Extract from exchanges config
    symbols: list[str] = []
    if hasattr(cfg, "exchanges") and cfg.exchanges:
        for exchange_cfg in cfg.exchanges.values():
            if hasattr(exchange_cfg, "pairs") and exchange_cfg.pairs:
                symbols.extend(exchange_cfg.pairs)

    return symbols[:5]  # Limit to 5 for performance


def _import_with_fallback(module_path: str, attr: str | None = None):
    """Import with fallback paths"""
    try:
        if attr:
            module = __import__(module_path, fromlist=[attr])
            return getattr(module, attr)
        else:
            return __import__(module_path)
    except ImportError:
        logger.warning(f"Failed to import {module_path}.{attr or ''}")
        return None


# --------------------- Node implementations ---------------------

async def fetch_context_node(state: TradingState) -> TradingState:
    """Aggregate global context and regime data"""
    with timer("fetch_context"):
        try:
            # Import AI engine modules
            global_context_mod = _import_with_fallback("ai_engine.global_context")
            regime_detector_mod = _import_with_fallback("ai_engine.regime_detector.deep_ta_analyzer")
            sentiment_mod = _import_with_fallback("ai_engine.regime_detector.sentiment_analyzer")
            macro_mod = _import_with_fallback("ai_engine.regime_detector.macro_analyzer")

            context_data: dict[str, Any] = {}

            # Global context
            if global_context_mod and hasattr(global_context_mod, "get_current_context"):
                context_data["global"] = await global_context_mod.get_current_context()

            # Regime detection
            if regime_detector_mod and hasattr(regime_detector_mod, "analyze_regime"):
                context_data["regime"] = await regime_detector_mod.analyze_regime()

            # Sentiment analysis
            if sentiment_mod and hasattr(sentiment_mod, "get_sentiment"):
                context_data["sentiment"] = await sentiment_mod.get_sentiment()

            # Macro analysis
            if macro_mod and hasattr(macro_mod, "get_macro_indicators"):
                context_data["macro"] = await macro_mod.get_macro_indicators()

            state.context = context_data

            # Create and push metric
            metric = MetricsTick(
                pnl={"realized": 0.0, "unrealized": 0.0, "fees": 0.0},
                slippage_bps_p50=0.0,
                latency_ms_p95=50.0,
                win_rate_1h=0.5,
                drawdown_daily=0.0,
                errors_rate=0.0,
            )
            state.push_metric(metric)
            await _publish_metric(metric)

        except Exception as e:
            state.add_error(f"fetch_context failed: {e}")

        await _checkpoint_state(state, "fetch_context")
        return state


async def scan_market_node(state: TradingState) -> TradingState:
    """Scan market for candidate symbols"""
    with timer("scan_market"):
        try:
            cfg = _get_config()

            # Import market scanner
            scanner_mod = _import_with_fallback("agents.core.market_scanner")

            candidates: list[str] = []
            if scanner_mod and hasattr(scanner_mod, "scan_candidates"):
                candidates = await scanner_mod.scan_candidates(limit=5)
            else:
                # Fallback to config symbols
                candidates = _get_symbols_from_config(cfg)

            state.scanned = candidates[:5]  # Limit for performance
            logger.info(f"Scanned {len(state.scanned)} candidates: {state.scanned}")

        except Exception as e:
            state.add_error(f"scan_market failed: {e}")
            # Fallback to default symbols
            state.scanned = ["BTC/USD", "ETH/USD"]

        await _checkpoint_state(state, "scan_market")
        return state


async def analyze_signals_node(state: TradingState) -> TradingState:
    """Analyze signals for scanned candidates"""
    with timer("analyze_signals"):
        try:
            cfg = _get_config()
            filters = default_filters_from_cfg(cfg)
            analyst_mod = _import_with_fallback("agents.core.signal_analyst")

            for symbol in state.scanned:
                try:
                    # Generate signal via analyst
                    raw_signal_data: dict[str, Any] | None = None
                    if analyst_mod and hasattr(analyst_mod, "analyze_symbol"):
                        try:
                            raw_signal_data = await asyncio.wait_for(
                                analyst_mod.analyze_symbol(symbol), timeout=5.0
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"Symbol analysis timed out for {symbol}")
                            continue

                    if not raw_signal_data:
                        continue

                    # Build FeatureFrame
                    ff = FeatureFrame(
                        symbol=symbol,
                        timeframe=raw_signal_data.get("timeframe", "5m"),
                        timestamp=time.time(),
                        price=float(raw_signal_data.get("price", 0.0)),
                        extra={"volume": float(raw_signal_data.get("volume", 0.0))},
                    )

                    # Normalize side
                    side_str = str(raw_signal_data.get("side", "buy")).lower()
                    side = "buy" if side_str == "buy" else "sell"

                    # Build SignalPlan
                    plan = SignalPlan(
                        symbol=symbol,
                        timeframe=ff.timeframe,
                        side=side,
                        confidence=float(raw_signal_data.get("confidence", 0.7)),
                        features={"price": ff.price, **ff.extra},
                        throttle_key=f"{symbol}:{ff.timeframe}:{side}",
                        idempotency_key=f"{symbol}:{ff.timeframe}:{side}:{int(ff.timestamp)//max(1, filters.throttle_s)}",
                        tags={"strategy": str(raw_signal_data.get("strategy", "trend_following"))},
                    )

                    # Process through signal pipeline
                    outcome = await process_signal(
                        plan,
                        ff,
                        filters,
                        cfg=cfg,
                        dry_run=getattr(cfg.orchestrator, "dry_run", True)
                        if hasattr(cfg, "orchestrator")
                        else True,
                    )

                    # Create Signal object for state tracking
                    signal = Signal(
                        strategy=plan.tags.get("strategy", "trend_following"),
                        symbol=plan.symbol,
                        timeframe=plan.timeframe,
                        side=OrderSide.BUY if plan.side == "buy" else OrderSide.SELL,
                        confidence=plan.confidence,
                        features=plan.features,
                    )

                    # Always track raw signal
                    state.raw_signals.append(signal)

                    # Only keep filtered signals if allowed
                    if outcome.get("allowed", False):
                        state.filtered_signals.append(signal)

                except Exception as e:
                    state.add_error(f"analyze_signals for {symbol} failed: {e}")
                    continue

            logger.info(f"Generated {len(state.raw_signals)} raw, {len(state.filtered_signals)} filtered signals")

        except Exception as e:
            state.add_error(f"analyze_signals failed: {e}")

        await _checkpoint_state(state, "analyze_signals")
        return state


async def risk_and_compliance_node(state: TradingState) -> TradingState:
    """Risk and compliance filtering"""
    with timer("risk_compliance"):
        try:
            cfg = _get_config()

            # Import risk modules
            health_mod = _import_with_fallback("agents.infrastructure.api_health_monitor")

            # Check system health
            if health_mod and hasattr(health_mod, "check_health"):
                try:
                    health_result = await asyncio.wait_for(health_mod.check_health(), timeout=3.0)
                    health_ok = health_result.get("healthy", False) if isinstance(health_result, dict) else bool(health_result)
                    if not health_ok:
                        state.add_error("System health check failed")
                        state.filtered_signals = []
                        await _checkpoint_state(state, "risk_compliance")
                        return state
                except asyncio.TimeoutError:
                    logger.warning("Health check timed out")

            # Filter signals through pretrade checks
            approved_signals: list[Signal] = []
            for signal in state.filtered_signals:
                try:
                    # Build RiskContext
                    features = signal.features or {}
                    ctx = RiskContext(
                        symbol=signal.symbol,
                        timeframe=signal.timeframe,
                        price=float(features.get("price", 0.0)),
                        bid=features.get("bid"),
                        ask=features.get("ask"),
                        balance_quote=0.0,
                        balance_base=0.0,
                        position_size=0.0,
                        realized_pnl=0.0,
                        unrealized_pnl=0.0,
                        recent_returns=[],
                        equity=(getattr(cfg, "equity", 0.0) or 100_000.0),
                        leverage=None,
                    )

                    decision = await pretrade_check(signal=signal, ctx=ctx, cfg=cfg)
                    if getattr(decision, "allowed", False):
                        approved_signals.append(signal)
                    else:
                        reasons = getattr(decision, "reasons", ["Unknown reason"])
                        logger.info(f"Signal blocked: {reasons}")

                except Exception as e:
                    state.add_error(f"pretrade_check failed for {signal.symbol}: {e}")

            state.filtered_signals = approved_signals
            logger.info(f"Risk filtered to {len(state.filtered_signals)} signals")

        except Exception as e:
            state.add_error(f"risk_and_compliance failed: {e}")

        await _checkpoint_state(state, "risk_compliance")
        return state


async def strategy_select_node(state: TradingState) -> TradingState:
    """Select trading strategy"""
    with timer("strategy_select"):
        try:
            if not state.filtered_signals:
                logger.info("No signals to select strategy for")
                await _checkpoint_state(state, "strategy_select")
                return state

            selector_mod = _import_with_fallback("ai_engine.strategy_selector")

            if selector_mod and hasattr(selector_mod, "select_strategy"):
                try:
                    selection = await asyncio.wait_for(
                        selector_mod.select_strategy(signals=state.filtered_signals, context=state.context),
                        timeout=10.0,
                    )
                    state.selected = {
                        "strategy": selection.get("strategy", "trend_following"),
                        "rationale": selection.get("rationale", "Default selection"),
                        "confidence": selection.get("confidence", 0.7),
                    }
                except asyncio.TimeoutError:
                    logger.warning("Strategy selection timed out, using fallback")
                    state.selected = {
                        "strategy": "trend_following",
                        "rationale": "Timeout fallback strategy",
                        "confidence": 0.6,
                    }
            else:
                # Fallback strategy selection
                state.selected = {"strategy": "trend_following", "rationale": "Fallback strategy", "confidence": 0.6}

            logger.info(
                f"Selected strategy: {state.selected['strategy']} (confidence: {state.selected['confidence']})"
            )

        except Exception as e:
            state.add_error(f"strategy_select failed: {e}")
            state.selected = {"strategy": "trend_following", "rationale": "Error fallback", "confidence": 0.5}

        await _checkpoint_state(state, "strategy_select")
        return state


async def execute_node(state: TradingState) -> TradingState:
    """Execute trading orders"""
    with timer("execute"):
        try:
            if not state.filtered_signals or not state.selected:
                logger.info("No signals or strategy selected for execution")
                await _checkpoint_state(state, "execute")
                return state

            cfg = _get_config()

            # Take first signal for simplicity
            signal = state.filtered_signals[0]

            # Build order intent
            order_intent = build_order_intent(signal, cfg)
            state.order_intent = order_intent

            # Centralized dry_run logic
            dry_run = getattr(cfg.orchestrator, "dry_run", True) if hasattr(cfg, "orchestrator") else True
            dry_run = dry_run or os.getenv("ORCHESTRATOR_DRY_RUN", "true").lower() == "true"

            # Get exchange (will be injected in real usage)
            exchange = NullExchange()  # Default fallback

            order_result = await send_intent(order_intent, cfg, exchange=exchange, dry_run=dry_run)
            state.order_ack = order_result

            logger.info(f"Order executed: {order_result.get('status', 'unknown')} (dry_run={dry_run})")

            # Publish to streams (best-effort)
            try:
                redis_mgr = await _get_redis()
                intent_data = pack_stream_fields(serialize_event(order_intent))
                await redis_mgr.client.xadd(
                    STREAMS["order_intent"], intent_data, maxlen=10000, approximate=True
                )

                ack_data = pack_stream_fields(order_result)
                await redis_mgr.client.xadd(STREAMS["order_ack"], ack_data, maxlen=10000, approximate=True)
            except Exception as e:
                logger.warning(f"Failed to publish order events: {e}")

        except Exception as e:
            state.add_error(f"execute failed: {e}")

        await _checkpoint_state(state, "execute")
        return state


async def monitor_node(state: TradingState) -> TradingState:
    """Monitor performance and emit metrics"""
    with timer("monitor"):
        try:
            monitor_mod = _import_with_fallback("agents.core.performance_monitor")

            # Calculate basic metrics
            pnl_data = {"realized": 0.0, "unrealized": 0.0, "fees": 0.0}
            error_rate = len(state.errors) / max(1, len(state.raw_signals))

            if monitor_mod and hasattr(monitor_mod, "calculate_metrics"):
                try:
                    metrics_data = await asyncio.wait_for(monitor_mod.calculate_metrics(), timeout=5.0)
                    if metrics_data:
                        pnl_data = metrics_data.get("pnl", pnl_data)
                except asyncio.TimeoutError:
                    logger.warning("Performance monitor timed out")

            # Create comprehensive metric
            metric = MetricsTick(
                pnl=pnl_data,
                slippage_bps_p50=2.5,
                latency_ms_p95=85.0,
                win_rate_1h=0.65,
                drawdown_daily=-0.005,
                errors_rate=error_rate,
            )

            state.push_metric(metric)
            await _publish_metric(metric)

            logger.info(f"Monitoring complete: {len(state.metrics)} metrics recorded")

        except Exception as e:
            state.add_error(f"monitor failed: {e}")
            # Still emit a basic metric on error
            basic_metric = MetricsTick(
                pnl={"realized": 0.0, "unrealized": 0.0, "fees": 0.0},
                slippage_bps_p50=0.0,
                latency_ms_p95=0.0,
                win_rate_1h=0.0,
                drawdown_daily=0.0,
                errors_rate=1.0,
            )
            state.push_metric(basic_metric)

        await _checkpoint_state(state, "monitor")
        return state


async def learn_node(state: TradingState) -> TradingState:
    """Learn from execution results"""
    with timer("learn"):
        try:
            learner_mod = _import_with_fallback("ai_engine.adaptive_learner")

            if learner_mod and hasattr(learner_mod, "update_model"):
                # Prepare learning data
                learning_data = {
                    "signals": [s.model_dump() for s in state.raw_signals],
                    "selected_strategy": state.selected,
                    "order_result": state.order_ack,
                    "metrics": [m.model_dump() for m in state.metrics],
                    "errors": state.errors,
                }

                # Non-blocking learning update with timeout
                try:
                    await asyncio.wait_for(learner_mod.update_model(learning_data), timeout=5.0)
                    logger.info("Learning update completed")
                except asyncio.TimeoutError:
                    logger.warning("Learning update timed out")
            else:
                logger.info("Adaptive learner not available")

        except Exception as e:
            state.add_error(f"learn failed: {e}")

        await _checkpoint_state(state, "learn")
        return state


# --------------------- Conditional routing ---------------------

def should_execute(state: TradingState) -> str:
    """Route to execute if we have filtered signals, otherwise skip to monitor"""
    if state.filtered_signals and state.selected:
        return "execute_node"
    return "monitor_node"


def should_continue_after_risk(state: TradingState) -> str:
    """Continue to strategy selection after risk checks"""
    return "strategy_select_node"


# --------------------- Graph wrapper ---------------------

class TradingGraph:
    """LangGraph-based trading orchestrator"""

    def __init__(self, cfg: Any | None = None, exchange: ExchangePort | None = None):
        self.cfg = cfg or _get_config()
        self.exchange = exchange or NullExchange()
        self._graph: CompiledGraphT | None = None
        self._redis_client = None
        # Centralize dry_run resolution
        self.dry_run = getattr(self.cfg.orchestrator, "dry_run", True) if hasattr(self.cfg, "orchestrator") else True
        self.dry_run = self.dry_run or os.getenv("ORCHESTRATOR_DRY_RUN", "true").lower() == "true"

    def build(self) -> CompiledGraphT:
        """Build and compile the trading graph"""
        if StateGraph is None:
            raise ImportError("LangGraph not installed. Install with: pip install langgraph")

        # Create graph
        workflow = StateGraph(TradingState)  # type: ignore[operator]

        # Add nodes
        workflow.add_node("fetch_context_node", fetch_context_node)
        workflow.add_node("scan_market_node", scan_market_node)
        workflow.add_node("analyze_signals_node", analyze_signals_node)
        workflow.add_node("risk_and_compliance_node", risk_and_compliance_node)
        workflow.add_node("strategy_select_node", strategy_select_node)
        workflow.add_node("execute_node", execute_node)
        workflow.add_node("monitor_node", monitor_node)
        workflow.add_node("learn_node", learn_node)

        # Add edges
        workflow.add_edge(START, "fetch_context_node")  # type: ignore[arg-type]
        workflow.add_edge("fetch_context_node", "scan_market_node")
        workflow.add_edge("scan_market_node", "analyze_signals_node")
        workflow.add_edge("analyze_signals_node", "risk_and_compliance_node")
        workflow.add_edge("risk_and_compliance_node", "strategy_select_node")

        # Conditional routing
        workflow.add_conditional_edges(
            "strategy_select_node",
            should_execute,
            {
                "execute_node": "execute_node",
                "monitor_node": "monitor_node",
            },
        )

        workflow.add_edge("execute_node", "monitor_node")
        workflow.add_edge("monitor_node", "learn_node")
        workflow.add_edge("learn_node", END)  # type: ignore[arg-type]

        self._graph = workflow.compile()
        return self._graph

    async def run_once(self, overrides: dict | None = None) -> TradingState:
        """Run one complete pass of the trading loop"""
        if self._graph is None:
            self._graph = self.build()

        # Initialize state
        initial_state = TradingState()

        # Apply overrides
        if overrides:
            for key, value in overrides.items():
                if hasattr(initial_state, key):
                    setattr(initial_state, key, value)

        logger.info(f"Starting trading run: {initial_state.run_id}")

        try:
            # Execute graph
            result: TradingState = await self._graph.ainvoke(initial_state)  # type: ignore[union-attr]

            duration = (datetime.now(timezone.utc) - initial_state.ts_start).total_seconds()
            logger.info(f"Trading run completed in {duration:.2f}s with {len(result.errors)} errors")

            return result

        except Exception as e:
            logger.error(f"Trading run failed: {e}")
            initial_state.add_error(f"Graph execution failed: {e}")
            return initial_state

    async def aclose(self) -> None:
        """Clean shutdown"""
        global _redis_manager
        if _redis_manager:
            await _redis_manager.close()
            _redis_manager = None


# --------------------- Public API ---------------------

def build_graph(cfg: Any | None = None) -> tuple[CompiledGraphT, TradingState]:
    """Build graph and return with initial state"""
    graph_instance = TradingGraph(cfg)
    compiled_graph = graph_instance.build()
    initial_state = TradingState()
    return compiled_graph, initial_state


async def run_once(cfg: Any | None = None, overrides: dict | None = None) -> TradingState:
    """Run one complete trading iteration"""
    graph_instance = TradingGraph(cfg)
    return await graph_instance.run_once(overrides)


# --------------------- CLI entry point ---------------------

if __name__ == "__main__":
    async def main():
        iterations = int(os.getenv("TRADING_GRAPH_ITER", "1"))
        dry_run = os.getenv("ORCHESTRATOR_DRY_RUN", "true").lower() == "true"

        logger.info(f"Starting {iterations} trading iterations (dry_run={dry_run})")

        graph = TradingGraph()

        try:
            for i in range(iterations):
                logger.info(f"=== Iteration {i + 1}/{iterations} ===")

                overrides = {}
                if dry_run:
                    overrides["dry_run"] = True

                result = await graph.run_once(overrides)

                # Summary
                logger.info(f"Iteration {i + 1} complete:")
                logger.info(f"  Scanned: {len(result.scanned)} symbols")
                logger.info(f"  Signals: {len(result.raw_signals)} raw, {len(result.filtered_signals)} filtered")
                logger.info(f"  Strategy: {result.selected.get('strategy', 'none')}")
                logger.info(f"  Executed: {'yes' if result.order_ack else 'no'}")
                logger.info(f"  Metrics: {len(result.metrics)}")
                logger.info(f"  Errors: {len(result.errors)}")

                if i < iterations - 1:
                    await asyncio.sleep(1)  # Brief pause between iterations

        except KeyboardInterrupt:
            logger.info("Graceful shutdown initiated...")
        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            await graph.aclose()
            logger.info("Trading graph shutdown complete")

    asyncio.run(main())

    async def build_trading_graph(cfg):
        graph, _ = build_graph(cfg)
        return graph
