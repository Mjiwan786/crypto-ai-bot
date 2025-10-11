# Protections & Risk Integration Guide

## Overview

This document explains how `protections/` and `risk/` modules integrate to provide comprehensive risk management without duplication.

## Architecture

```
agents/
├── risk/                          # Core risk decisions (REUSABLE)
│   ├── drawdown_protector.py     ✅ Pure logic, no I/O
│   ├── compliance_checker.py     ✅ Pure logic, no I/O
│   ├── portfolio_balancer.py     ✅ Pure logic, no I/O
│   └── risk_router.py             ✅ Orchestrates all risk modules
│
└── scalper/
    ├── risk/
    │   └── limits.py              ⚠️ Duplicates some risk logic (NEEDS CLEANUP)
    │
    └── protections/
        ├── circuit_breakers.py    ✅ Wires triggers, uses agents/risk
        └── kill_switches.py       ✅ Emergency controls
```

## Integration Strategy

### 1. **agents/risk/** - Core Risk Decisions (CENTRAL)

**Purpose:** Pure, reusable risk logic

**Characteristics:**
- ✅ Pure functions - no I/O dependencies
- ✅ Deterministic - same input → same output
- ✅ Protocol-based - easy to test with fakes
- ✅ Comprehensive testing (76% pass rate, 48/63 tests)
- ✅ Used by ALL agents (not just scalper)

**Key Modules:**

#### `agents/risk/drawdown_protector.py`
```python
class DrawdownProtector:
    """
    Multi-scope drawdown protection.

    Features:
    - Portfolio, strategy, symbol-level monitoring
    - 4-state machine: NORMAL → WARN → SOFT_STOP → HARD_HALT
    - Rolling window drawdown tracking
    - Consecutive loss streak detection
    - Cooldown periods
    """

    def ingest_fill(self, e: FillEvent) -> None:
        """Update loss streaks from trade fills"""

    def ingest_snapshot(self, e: SnapshotEvent) -> None:
        """Update drawdown from equity snapshots"""

    def assess_can_open(self, strategy: str, symbol: str) -> GateDecision:
        """Assess if new positions can be opened"""
```

**Usage in Protections:**
```python
from agents.risk.drawdown_protector import DrawdownProtector, FillEvent

# Create protector with policy
protector = DrawdownProtector(policy=DrawdownBands(...))

# Feed trade fills
protector.ingest_fill(FillEvent(
    ts_s=int(time.time()),
    pnl_after_fees=trade_pnl,
    strategy="scalper",
    symbol="BTC/USD",
    won=trade_pnl > 0
))

# Check if trading allowed
decision = protector.assess_can_open("scalper", "BTC/USD")
if decision.halt_all:
    # Trigger circuit breaker
    await circuit_breaker.halt_system("Loss streak detected")
```

### 2. **scalper/protections/circuit_breakers.py** - Trigger Wiring

**Purpose:** Wire external signals to circuit breakers using agents/risk logic

**Enhancements Needed:**

#### **API Error Streak Trigger** 🚨
```python
class APIErrorTracker:
    """Track API errors and trigger circuit breaker on streak"""

    def __init__(self, breaker_manager: CircuitBreakerManager):
        self.breaker_manager = breaker_manager
        self.error_window: Deque[Tuple[float, str]] = deque(maxlen=100)
        self.total_calls = 0

    async def record_call(self, success: bool, error_type: Optional[str] = None):
        """Record API call outcome"""
        self.total_calls += 1
        now = time.time()

        if not success:
            self.error_window.append((now, error_type or "unknown"))

        # Calculate error rate over last 2 minutes
        cutoff = now - 120
        recent_errors = [(t, e) for (t, e) in self.error_window if t >= cutoff]

        if self.total_calls > 10:  # Min calls before checking
            error_rate = len(recent_errors) / self.total_calls * 100.0
            await self.breaker_manager.check_api_errors(error_rate)
```

#### **Latency P95 Breach Trigger** 🚨
```python
class LatencyMonitor:
    """Monitor API latency and trigger breaker on P95 breach"""

    def __init__(self, breaker_manager: CircuitBreakerManager):
        self.breaker_manager = breaker_manager
        self.latency_samples: Deque[float] = deque(maxlen=100)

    async def record_latency(self, latency_ms: float):
        """Record API call latency"""
        self.latency_samples.append(latency_ms)

        if len(self.latency_samples) >= 20:  # Min samples
            p95 = self._calculate_percentile(95)
            await self.breaker_manager.check_latency(p95)

    def _calculate_percentile(self, percentile: int) -> float:
        """Calculate percentile from samples"""
        sorted_samples = sorted(self.latency_samples)
        index = int(len(sorted_samples) * percentile / 100)
        return sorted_samples[min(index, len(sorted_samples) - 1)]
```

#### **Loss Streak Integration with agents/risk** 🚨
```python
class LossStreakIntegrator:
    """Bridge between agents/risk and circuit breakers"""

    def __init__(
        self,
        breaker_manager: CircuitBreakerManager,
        drawdown_protector: DrawdownProtector
    ):
        self.breaker_manager = breaker_manager
        self.drawdown_protector = drawdown_protector

    async def on_trade_close(
        self,
        pnl_after_fees: float,
        strategy: str,
        symbol: str
    ):
        """Process trade close through both systems"""
        # 1. Update agents/risk drawdown protector
        self.drawdown_protector.ingest_fill(FillEvent(
            ts_s=int(time.time()),
            pnl_after_fees=pnl_after_fees,
            strategy=strategy,
            symbol=symbol,
            won=pnl_after_fees > 0
        ))

        # 2. Check if circuit breaker should trigger
        decision = self.drawdown_protector.assess_can_open(strategy, symbol)

        if decision.halt_all:
            # Trigger circuit breaker halt
            await self.breaker_manager.halt_system(
                f"Loss streak triggered: {decision.reason}",
                duration_seconds=1800  # 30 min
            )
        elif decision.reduce_only:
            # Trigger soft stop (no new positions)
            if BreakerType.LOSS in self.breaker_manager.breakers:
                await self.breaker_manager.breakers[BreakerType.LOSS].force_open(
                    f"Soft stop: {decision.reason}",
                    duration_seconds=600  # 10 min
                )
```

### 3. **scalper/risk/limits.py** - TO BE REFACTORED

**Current State:** Duplicates some logic from `agents/risk`

**Issues:**
- ⚠️ `RiskLimits` class duplicates portfolio-level limits
- ⚠️ `PositionLimits` overlaps with `portfolio_balancer.py`
- ⚠️ `DynamicRiskAdjuster` not integrated with drawdown protector

**Refactoring Plan:**

#### **Step 1: Thin Wrapper Pattern**
```python
# agents/scalper/risk/limits.py (REFACTORED)

from agents.risk.portfolio_balancer import PortfolioBalancer, BalancerConfig
from agents.risk.drawdown_protector import DrawdownProtector, DrawdownBands

class ScalperRiskLimits:
    """
    Thin wrapper around agents/risk modules for scalper-specific configuration.

    Delegates actual decisions to agents/risk.
    """

    def __init__(self, config: KrakenScalpingConfig):
        self.config = config

        # Initialize agents/risk modules with scalper config
        self.balancer = PortfolioBalancer(config=BalancerConfig(
            max_total_exposure_usd=config.risk.max_total_exposure_usd,
            per_symbol_cap_pct=config.risk.per_symbol_max_exposure,
            # ... map config fields
        ))

        self.drawdown_protector = DrawdownProtector(policy=DrawdownBands(
            daily_stop_pct=config.risk.daily_stop_loss,
            max_consecutive_losses=3,
            # ... map config fields
        ))

    def get_max_position_size(self, symbol: str, current_price: float) -> float:
        """Delegate to portfolio balancer"""
        return self.balancer.calculate_max_position_size(symbol, current_price)

    def is_within_daily_limits(self, current_pnl_usd: float) -> bool:
        """Delegate to drawdown protector"""
        decision = self.drawdown_protector.assess_can_open("scalper", "")
        return not decision.halt_all
```

#### **Step 2: Remove Duplicated Logic**
```python
# DELETE these classes (logic moved to agents/risk):
# - RiskLimits.max_daily_loss
# - RiskLimits.max_daily_drawdown
# - RiskLimits.max_total_exposure
# - PositionLimits.get_max_position_size (use portfolio_balancer)

# KEEP scalper-specific config mapping:
# - ScalperRiskLimits (thin wrapper)
# - Scalper-specific thresholds
```

## Complete Integration Example

```python
# agents/scalper/scalper_agent.py

from agents.risk.drawdown_protector import DrawdownProtector, DrawdownBands, FillEvent
from agents.risk.portfolio_balancer import PortfolioBalancer, BalancerConfig
from agents.scalper.protections.circuit_breakers import CircuitBreakerManager
from agents.scalper.protections.monitors import (
    APIErrorTracker, LatencyMonitor, LossStreakIntegrator
)

class ScalperAgent:
    def __init__(self, config: KrakenScalpingConfig):
        # 1. Initialize agents/risk modules (CENTRAL DECISION LOGIC)
        self.drawdown_protector = DrawdownProtector(policy=DrawdownBands(
            daily_stop_pct=config.risk.daily_stop_loss,
            max_consecutive_losses=3,
            rolling_windows_pct=[(3600, -0.01), (14400, -0.015)],
        ))

        self.portfolio_balancer = PortfolioBalancer(config=BalancerConfig(
            max_total_exposure_usd=config.risk.max_total_exposure_usd,
            per_symbol_cap_pct=config.risk.per_symbol_max_exposure,
        ))

        # 2. Initialize circuit breakers (TRIGGER WIRING)
        self.circuit_breaker_manager = CircuitBreakerManager(
            config=config,
            redis_bus=self.redis_bus,
            agent_id=self.agent_id
        )

        # 3. Initialize monitors (WIRE TRIGGERS)
        self.api_error_tracker = APIErrorTracker(self.circuit_breaker_manager)
        self.latency_monitor = LatencyMonitor(self.circuit_breaker_manager)
        self.loss_streak_integrator = LossStreakIntegrator(
            self.circuit_breaker_manager,
            self.drawdown_protector
        )

    async def on_trade_close(self, trade: Trade):
        """Process trade close through integrated systems"""
        # Update loss streak tracker (agents/risk)
        await self.loss_streak_integrator.on_trade_close(
            pnl_after_fees=trade.pnl,
            strategy="scalper",
            symbol=trade.symbol
        )

        # Update equity snapshot (agents/risk)
        self.drawdown_protector.ingest_snapshot(SnapshotEvent(
            ts_s=int(time.time()),
            equity_start_of_day_usd=self.starting_equity,
            equity_current_usd=self.current_equity,
        ))

    async def execute_api_call(self, call: Callable):
        """Execute API call with monitoring"""
        start = time.time()
        try:
            result = await call()
            latency_ms = (time.time() - start) * 1000

            # Record success
            await self.api_error_tracker.record_call(success=True)
            await self.latency_monitor.record_latency(latency_ms)

            return result
        except Exception as e:
            latency_ms = (time.time() - start) * 1000

            # Record error
            await self.api_error_tracker.record_call(
                success=False,
                error_type=type(e).__name__
            )
            await self.latency_monitor.record_latency(latency_ms)
            raise

    async def can_open_position(self, symbol: str) -> Tuple[bool, str]:
        """Check if position can be opened"""
        # 1. Check circuit breakers
        if self.circuit_breaker_manager.is_any_breaker_open():
            return False, "Circuit breaker open"

        # 2. Check drawdown protector (agents/risk)
        decision = self.drawdown_protector.assess_can_open("scalper", symbol)
        if decision.halt_all:
            return False, f"Drawdown halt: {decision.reason}"
        if decision.reduce_only:
            return False, f"Reduce only: {decision.reason}"

        # 3. Check portfolio balancer (agents/risk)
        max_size = self.portfolio_balancer.calculate_max_position_size(
            symbol, current_price=self.get_current_price(symbol)
        )
        if max_size <= 0:
            return False, "Exposure limit reached"

        return True, "OK"
```

## Trigger Mapping

| Trigger | Module | Integration Point |
|---------|--------|-------------------|
| **API Error Streak** | `protections/monitors.py` → `circuit_breakers.py` | `APIErrorTracker.record_call()` |
| **Latency P95 Breach** | `protections/monitors.py` → `circuit_breakers.py` | `LatencyMonitor.record_latency()` |
| **Loss Streak** | `agents/risk/drawdown_protector.py` → `circuit_breakers.py` | `LossStreakIntegrator.on_trade_close()` |
| **Drawdown Breach** | `agents/risk/drawdown_protector.py` | `DrawdownProtector.ingest_snapshot()` |
| **Position Size** | `agents/risk/portfolio_balancer.py` | `PortfolioBalancer.calculate_max_position_size()` |

## Testing Strategy

### Unit Tests (Pure Logic)
```python
# test_risk_integration.py

def test_loss_streak_triggers_circuit_breaker():
    """Test loss streak integration"""
    protector = DrawdownProtector(policy=DrawdownBands(
        max_consecutive_losses=3
    ))
    breaker = CircuitBreaker("loss", BreakerType.LOSS, config)

    # Simulate 3 losing trades
    for i in range(3):
        protector.ingest_fill(FillEvent(
            ts_s=int(time.time()),
            pnl_after_fees=-10.0,
            strategy="scalper",
            symbol="BTC/USD",
            won=False
        ))

    # Check decision
    decision = protector.assess_can_open("scalper", "BTC/USD")
    assert decision.reduce_only or decision.halt_all
```

### Integration Tests
```python
# test_integrated_systems.py

async def test_api_error_triggers_breaker():
    """Test API error tracking triggers circuit breaker"""
    manager = CircuitBreakerManager(config, redis_bus)
    tracker = APIErrorTracker(manager)

    # Simulate error streak
    for _ in range(10):
        await tracker.record_call(success=False, error_type="RateLimitError")

    # Check breaker state
    assert manager.is_any_breaker_open()
```

## Migration Checklist

### Phase 1: Wire Triggers ✅
- [x] Create `APIErrorTracker`
- [x] Create `LatencyMonitor`
- [x] Create `LossStreakIntegrator`
- [x] Update `CircuitBreakerManager` to accept trackers

### Phase 2: Integrate agents/risk 🚧
- [ ] Refactor `scalper/risk/limits.py` to thin wrapper
- [ ] Remove duplicated logic from `limits.py`
- [ ] Add integration tests
- [ ] Update scalper agent to use integrated systems

### Phase 3: Documentation ✅
- [x] Create integration guide
- [x] Document trigger wiring
- [x] Provide usage examples
- [x] Add testing strategy

## References

- **agents/risk/RISK_TESTS_SUMMARY.md** - Comprehensive risk module tests
- **agents/risk/drawdown_protector.py** - Pure drawdown protection logic
- **agents/scalper/protections/circuit_breakers.py** - Trigger wiring
- **config/config_loader.py** - Configuration management
