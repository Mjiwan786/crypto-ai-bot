# Scalper Module Refactoring Plan

## Overview

Refactor analysis and execution modules to follow clean architecture principles:
- **Pure functions** with no hidden state
- **Protocol-based interfaces** for easy testing
- **Deterministic outputs** for given inputs
- **External state** passed explicitly

## Current State Analysis

### ✅ Good Practices Already Present
1. **Dataclasses** for DTOs (OrderBookSnapshot, TradeEvent, OrderRequest, etc.)
2. **Type hints** throughout
3. **Error handling** with try-except blocks
4. **Comprehensive logging**
5. **Performance tracking** with deques

### ❌ Issues to Fix

#### 1. **analysis/liquidity.py** - Needs Pure Function Extraction
**Current Issues:**
- `LiquidityAnalyzer` stores state (`orderbook_history`, `metrics_history`)
- Methods are async but don't need to be (no I/O)
- Config dependency makes testing harder

**Refactoring:**
```python
# BEFORE (stateful class)
class LiquidityAnalyzer:
    def __init__(self, config, agent_id):
        self.orderbook_history = {}  # STATE!
        self.metrics_history = {}    # STATE!

    async def analyze_orderbook(self, book):
        self._store_snapshot(book)  # side effect
        ...

# AFTER (pure functions)
def calculate_liquidity_metrics(
    orderbook: OrderBookSnapshot,
    depth_levels: int = 10
) -> LiquidityMetrics:
    """Pure function: same input → same output"""
    basic = _calculate_basic_metrics(orderbook, depth_levels)
    advanced = _calculate_advanced_metrics(orderbook, depth_levels)
    ...
    return LiquidityMetrics(...)

def estimate_market_impact(
    orderbook: OrderBookSnapshot,
    side: str,
    size_btc: float,
    model_params: ImpactModelParams
) -> MarketImpactEstimate:
    """Pure parametric model"""
    ...

# Stateful wrapper (if needed)
class LiquidityHistory:
    def __init__(self, max_snapshots: int = 100):
        self.snapshots: deque[OrderBookSnapshot] = deque(maxlen=max_snapshots)

    def add(self, snapshot: OrderBookSnapshot):
        self.snapshots.append(snapshot)

    def get_stability_metrics(self) -> StabilityMetrics:
        return calculate_stability_metrics(list(self.snapshots))
```

#### 2. **analysis/order_flow.py** - Reduce State, Extract Pure Logic
**Current Issues:**
- `OrderFlowAnalyzer` has mutable state (`trades`, `flow_metrics`)
- `_calculate_window_metrics` is almost pure but buried in class
- Logger/metrics dependencies make unit testing hard

**Refactoring:**
```python
# BEFORE (stateful)
class OrderFlowAnalyzer:
    def __init__(self, config):
        self.trades = {}  # STATE!
        self.flow_metrics = {}  # STATE!

    async def process_trade(self, trade_data):
        self.trades[pair].append(trade_event)  # mutation
        await self._update_flow_metrics(pair)  # async for no reason

# AFTER (pure core + thin wrapper)
@dataclass
class OrderFlowConfig:
    analysis_windows: List[int] = field(default_factory=lambda: [10, 30, 60, 300])
    large_trade_btc: float = 0.5
    strong_imbalance_threshold: float = 0.7

def calculate_flow_metrics(
    trades: List[TradeEvent],
    window_seconds: int,
    config: OrderFlowConfig
) -> Optional[FlowMetrics]:
    """Pure function: deterministic flow calculation"""
    if not trades:
        return None

    # All calculations are pure
    buy_volume = sum(t.volume for t in trades if t.direction == TradeDirection.BUY)
    sell_volume = sum(t.volume for t in trades if t.direction == TradeDirection.SELL)
    ...
    return FlowMetrics(...)

def generate_flow_signal(
    volume_imbalance: float,
    trade_imbalance: float,
    price_change_bps: float,
    large_trade_ratio: float,
    config: OrderFlowConfig
) -> Tuple[FlowSignal, float]:
    """Pure signal generation"""
    flow_score = 0.4 * volume_imbalance + 0.3 * trade_imbalance + ...
    flow_strength = min(1.0, abs(flow_score))

    if flow_score >= config.strong_imbalance_threshold:
        return FlowSignal.STRONG_BUY, flow_strength
    ...

# Thin stateful wrapper (if needed for streaming)
class OrderFlowStream:
    def __init__(self, config: OrderFlowConfig, max_history: int = 10000):
        self.trades: Dict[str, deque[TradeEvent]] = defaultdict(
            lambda: deque(maxlen=max_history)
        )
        self.config = config

    def add_trade(self, trade: TradeEvent) -> None:
        self.trades[trade.pair].append(trade)

    def get_metrics(self, pair: str, window_seconds: int) -> Optional[FlowMetrics]:
        cutoff = time.time() - window_seconds
        recent_trades = [t for t in self.trades[pair] if t.timestamp >= cutoff]
        return calculate_flow_metrics(recent_trades, window_seconds, self.config)
```

#### 3. **execution/kraken_gateway.py** - Interface + Error Classification
**Current Issues:**
- Direct CCXT/HTTP implementation (hard to test)
- No Protocol interface
- Error handling doesn't classify (retryable vs fatal)

**Refactoring:**
```python
# BEFORE (concrete implementation)
class KrakenGateway:
    async def place_order(self, request):
        response = await self._make_request("POST", "AddOrder", ...)
        # No error classification

# AFTER (protocol + implementation)
from typing import Protocol

class ExchangeError(Exception):
    """Base exchange error"""
    def __init__(self, message: str, retryable: bool = False, code: str = ""):
        super().__init__(message)
        self.retryable = retryable
        self.code = code

class RateLimitError(ExchangeError):
    def __init__(self, message: str):
        super().__init__(message, retryable=True, code="RATE_LIMIT")

class InvalidOrderError(ExchangeError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False, code="INVALID_ORDER")

class InsufficientFundsError(ExchangeError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False, code="INSUFFICIENT_FUNDS")

class NetworkError(ExchangeError):
    def __init__(self, message: str):
        super().__init__(message, retryable=True, code="NETWORK")

class ExchangeGatewayProtocol(Protocol):
    """Protocol for exchange gateways"""
    async def place_order(self, request: OrderRequest) -> OrderResponse: ...
    async def cancel_order(self, order_id: str) -> bool: ...
    async def get_order_status(self, order_id: str) -> Optional[OrderResponse]: ...
    async def get_ticker(self, symbol: str) -> Optional[Dict[str, float]]: ...

class KrakenGateway:
    """Kraken-specific implementation"""

    def _classify_error(self, error_msg: str) -> ExchangeError:
        """Classify Kraken errors"""
        msg_lower = error_msg.lower()

        # Rate limit
        if "rate limit" in msg_lower or "too many requests" in msg_lower:
            return RateLimitError(error_msg)

        # Invalid order
        if "invalid" in msg_lower or "unknown order" in msg_lower:
            return InvalidOrderError(error_msg)

        # Insufficient funds
        if "insufficient" in msg_lower or "balance" in msg_lower:
            return InsufficientFundsError(error_msg)

        # Network/timeout
        if "timeout" in msg_lower or "connection" in msg_lower:
            return NetworkError(error_msg)

        # Unknown = not retryable by default
        return ExchangeError(error_msg, retryable=False, code="UNKNOWN")

    async def place_order(self, request: OrderRequest) -> OrderResponse:
        try:
            ...
        except Exception as e:
            classified = self._classify_error(str(e))
            if classified.retryable:
                # Retry logic
                ...
            raise classified
```

#### 4. **execution/order_optimizer.py** - Extract Pure Functions
**Current Issues:**
- `OrderOptimizer` has state (`execution_history`, `optimization_metrics`)
- Decision logic buried in methods
- Models (`SlippageModel`, `TimingModel`) have state

**Refactoring:**
```python
# BEFORE (stateful)
class OrderOptimizer:
    def __init__(self, config):
        self.execution_history = []  # STATE!
        self.slippage_model = SlippageModel(config)  # has state

    async def optimize_order(self, request, conditions):
        tactic = self._select_execution_tactic(request, conditions)  # pure!
        ...

# AFTER (pure functions)
def select_execution_tactic(
    request: OrderRequest,
    market: MarketConditions,
    thresholds: TacticThresholds
) -> OrderTactic:
    """Pure tactic selection"""
    if market.spread_bps >= thresholds.min_spread_for_passive and market.volatility < thresholds.volatility_threshold:
        return OrderTactic.PASSIVE

    if market.spread_bps > thresholds.max_spread_for_aggressive:
        return OrderTactic.AGGRESSIVE

    notional = float(request.size) * float(request.price or 100.0)
    if notional > thresholds.iceberg_threshold_usd:
        return OrderTactic.ICEBERG

    return OrderTactic.SMART

def optimize_passive_order(
    request: OrderRequest,
    market: MarketConditions
) -> List[OrderRequest]:
    """Pure passive optimization"""
    optimal_price = _calculate_optimal_passive_price(request, market)
    return [OrderRequest(
        symbol=request.symbol,
        side=request.side,
        order_type="limit",
        size=request.size,
        price=optimal_price,
        post_only=True
    )]

def optimize_iceberg_order(
    request: OrderRequest,
    market: MarketConditions,
    sizing: IcebergSizing
) -> List[OrderRequest]:
    """Pure iceberg slicing"""
    slice_size = _calculate_slice_size(float(request.size), market, sizing)
    slices = []
    remaining = float(request.size)
    idx = 0

    while remaining > 1e-12:
        current = min(slice_size, remaining)
        slices.append(OrderRequest(...))
        remaining -= current
        idx += 1
        if idx > 10000:
            break

    return slices

# Thin wrapper
class OrderOptimizationEngine:
    def __init__(self, thresholds: TacticThresholds, sizing: IcebergSizing):
        self.thresholds = thresholds
        self.sizing = sizing

    def optimize(self, request: OrderRequest, market: MarketConditions) -> OptimizedOrder:
        tactic = select_execution_tactic(request, market, self.thresholds)

        if tactic == OrderTactic.PASSIVE:
            optimized = optimize_passive_order(request, market)
        elif tactic == OrderTactic.ICEBERG:
            optimized = optimize_iceberg_order(request, market, self.sizing)
        ...

        return OptimizedOrder(
            original_request=request,
            optimized_requests=optimized,
            tactic=tactic,
            ...
        )
```

#### 5. **execution/position_manager.py** - Idempotent Logic with External State
**Current Issues:**
- `PositionManager` is a stateful class (good for actual use, but hard to test)
- Core logic (sizing, PnL calculation) is buried in methods
- Needs external state version for testing

**Refactoring:**
```python
# Pure position calculations
@dataclass
class PositionSnapshot:
    """Immutable position state"""
    symbol: str
    side: PositionSide
    size: Decimal
    avg_price: Decimal
    current_price: Decimal
    realized_pnl: Decimal
    total_fees: Decimal

    @property
    def unrealized_pnl(self) -> Decimal:
        """Pure calculation"""
        if self.side == PositionSide.LONG:
            return (self.current_price - self.avg_price) * abs(self.size)
        else:
            return (self.avg_price - self.current_price) * abs(self.size)

    @property
    def total_pnl(self) -> Decimal:
        return self.realized_pnl + self.unrealized_pnl

def calculate_position_size(
    equity: float,
    risk_percentage: float,
    stop_loss_bps: int,
    signal_confidence: float,
    risk_score: float,
    volatility_multiplier: float,
    exposure_multiplier: float,
    sizing_config: PositionSizingConfig
) -> float:
    """Pure position sizing calculation"""
    base_size = sizing_config.base_size_usd

    risk_multiplier = max(0.10, 1.0 - max(0.0, min(1.0, risk_score)))
    confidence_multiplier = max(0.50, max(0.0, min(1.0, signal_confidence)))

    stop_loss_fraction = max(1e-6, abs(stop_loss_bps) / 10_000.0)
    risk_budget_usd = equity * risk_percentage
    risk_based_size = risk_budget_usd / stop_loss_fraction

    position_size = (
        base_size
        * risk_multiplier
        * confidence_multiplier
        * volatility_multiplier
        * exposure_multiplier
    )
    position_size = min(position_size, risk_based_size)

    # Limits
    position_size = max(sizing_config.min_size_usd, position_size)
    position_size = min(sizing_config.max_size_usd, position_size)

    return position_size

def compute_realized_pnl(
    position_side: PositionSide,
    entry_price: Decimal,
    exit_price: Decimal,
    size: Decimal
) -> Decimal:
    """Pure PnL calculation"""
    if position_side == PositionSide.LONG:
        return (exit_price - entry_price) * size
    else:
        return (entry_price - exit_price) * size

def add_to_position(
    current: PositionSnapshot,
    add_size: Decimal,
    add_price: Decimal
) -> PositionSnapshot:
    """Pure position addition (returns new snapshot)"""
    current_value = abs(current.size) * current.avg_price
    new_value = abs(add_size) * add_price
    total_size = abs(current.size) + abs(add_size)

    new_avg_price = (current_value + new_value) / total_size if total_size > 0 else add_price
    new_size = current.size + (add_size if current.side == PositionSide.LONG else -add_size)

    return PositionSnapshot(
        symbol=current.symbol,
        side=current.side,
        size=new_size,
        avg_price=new_avg_price,
        current_price=current.current_price,
        realized_pnl=current.realized_pnl,
        total_fees=current.total_fees
    )

# Stateful manager (uses pure functions internally)
class PositionManager:
    """Stateful position manager (uses pure functions internally)"""

    async def open_position(self, order_id, symbol, side, size, price, metadata):
        """Idempotent: same inputs → same final state"""
        async with self.position_lock:
            if symbol in self.positions:
                # Use pure function
                self.positions[symbol] = add_to_position(
                    self.positions[symbol],
                    Decimal(str(size)),
                    Decimal(str(price))
                )
            else:
                self.positions[symbol] = PositionSnapshot(...)

            self.current_prices[symbol] = price
            await self._update_metrics()
            return True
```

#### 6. **execution/slippage_model.py** - Parametric Model + Tests

**Create new file:**
```python
"""
Parametric slippage model for execution quality prediction.

Pure functions for slippage estimation based on market conditions.
"""

from dataclasses import dataclass
from typing import Optional

@dataclass
class SlippageModelParams:
    """Slippage model parameters"""
    base_slippage_bps: float = 2.0
    impact_size_coefficient: float = 0.5  # impact per 1000 USD
    volatility_multiplier: float = 10.0
    liquidity_factor: float = 1.0

def predict_market_order_slippage(
    spread_bps: float,
    notional_usd: float,
    volatility: float,
    volume_ratio: float,
    params: SlippageModelParams
) -> float:
    """
    Predict slippage for market order.

    Pure function: same inputs → same output

    Args:
        spread_bps: Current spread in basis points
        notional_usd: Order size in USD
        volatility: Current volatility (0-1 scale)
        volume_ratio: Current/average volume ratio
        params: Model parameters

    Returns:
        Predicted slippage in basis points
    """
    # Base: cross most of spread
    base_slippage = max(0.0, spread_bps * 0.8)

    # Size impact
    impact_factor = 1.0 + (notional_usd / 1000.0) * params.impact_size_coefficient

    # Volatility impact
    vol_factor = 1.0 + max(0.0, volatility) * params.volatility_multiplier

    # Liquidity impact
    liq_factor = params.liquidity_factor / max(0.5, volume_ratio)

    predicted = base_slippage * impact_factor * vol_factor * liq_factor
    return max(0.0, float(predicted))

def predict_limit_order_slippage(
    base_slippage_bps: float,
    distance_from_mid_bps: float,
    post_only: bool
) -> float:
    """
    Predict slippage for limit order.

    Args:
        base_slippage_bps: Base slippage assumption
        distance_from_mid_bps: How far limit is from mid price
        post_only: Whether post-only (maker-only)

    Returns:
        Predicted slippage in basis points
    """
    if post_only and distance_from_mid_bps > 0:
        # Maker order: negative slippage (rebate)
        return -abs(distance_from_mid_bps) * 0.5

    # Taker or at mid: base slippage applies
    return max(0.0, base_slippage_bps)

def calibrate_slippage_model(
    historical_data: List[Tuple[MarketConditions, float]]
) -> SlippageModelParams:
    """
    Calibrate model parameters from historical slippage data.

    Pure function: deterministic calibration
    """
    if not historical_data:
        return SlippageModelParams()

    # Simple linear regression or parameter fit
    # (placeholder: in production, use proper fitting)
    base_slippage = sum(slip for _, slip in historical_data) / len(historical_data)

    return SlippageModelParams(base_slippage_bps=base_slippage)
```

## Implementation Steps

1. ✅ **Extract pure functions from analysis modules**
   - Create `agents/scalper/analysis/liquidity_pure.py`
   - Create `agents/scalper/analysis/order_flow_pure.py`
   - Keep existing classes as thin wrappers

2. ✅ **Create exchange protocol + error classification**
   - Create `agents/scalper/execution/exchange_protocol.py`
   - Create `agents/scalper/execution/exchange_errors.py`
   - Update `kraken_gateway.py` to implement protocol

3. ✅ **Extract pure optimizer functions**
   - Create `agents/scalper/execution/order_optimizer_pure.py`
   - Keep `OrderOptimizer` as wrapper

4. ✅ **Extract pure position functions**
   - Create `agents/scalper/execution/position_pure.py`
   - Add `PositionSnapshot` immutable DTO
   - Keep `PositionManager` for stateful use

5. ✅ **Create slippage model + tests**
   - Create `agents/scalper/execution/slippage_model.py`
   - Create `tests/test_slippage_model.py`

6. ✅ **Update integration**
   - Update existing code to use new pure functions
   - Add unit tests for all pure functions
   - Document migration path

## Testing Strategy

### Unit Tests (Pure Functions)
```python
def test_calculate_liquidity_metrics():
    book = OrderBookSnapshot(
        symbol="BTC/USD",
        bids=[OrderBookLevel(50000, 1.0), OrderBookLevel(49999, 2.0)],
        asks=[OrderBookLevel(50001, 1.5), OrderBookLevel(50002, 2.5)]
    )

    metrics = calculate_liquidity_metrics(book, depth_levels=2)

    assert metrics.spread_bps > 0
    assert metrics.bid_depth_btc == 3.0
    assert metrics.ask_depth_btc == 4.0

def test_predict_market_order_slippage():
    params = SlippageModelParams(base_slippage_bps=2.0)

    slippage = predict_market_order_slippage(
        spread_bps=5.0,
        notional_usd=1000.0,
        volatility=0.02,
        volume_ratio=1.0,
        params=params
    )

    assert slippage > 0
    assert slippage < 20.0  # reasonable bounds
```

### Integration Tests (with Fakes)
```python
class FakeExchangeGateway:
    async def place_order(self, request):
        return OrderResponse(order_id="test_123", status="open", ...)

async def test_order_optimizer_with_fake():
    gateway = FakeExchangeGateway()
    optimizer = OrderOptimizationEngine(...)

    optimized = optimizer.optimize(request, market_conditions)

    for req in optimized.optimized_requests:
        response = await gateway.place_order(req)
        assert response.status in ("open", "filled")
```

## Success Criteria

- [ ] All analysis functions are pure (no I/O, deterministic)
- [ ] Exchange gateway implements protocol interface
- [ ] Error classification distinguishes retryable vs fatal
- [ ] Order optimizer uses pure functions
- [ ] Position manager has idempotent operations
- [ ] Slippage model is parametric with unit tests
- [ ] 100% test coverage for pure functions
- [ ] Integration tests use fakes (no network I/O)

## Migration Path

1. **Phase 1** (Week 1): Extract pure functions, keep existing classes
2. **Phase 2** (Week 2): Add protocol interfaces, error classification
3. **Phase 3** (Week 3): Write comprehensive unit tests
4. **Phase 4** (Week 4): Migrate existing code to use new functions
5. **Phase 5** (Week 5): Remove old stateful code, document

## Benefits

- **Testability**: Pure functions easy to unit test
- **Determinism**: Same inputs → same outputs
- **Composability**: Functions can be combined easily
- **Maintainability**: Clear separation of concerns
- **Performance**: No hidden I/O in pure functions
