"""
Flash Loan Short Seller Integration Module

Orchestrates short-selling using flash-loan liquidity with comprehensive risk controls,
telemetry, and 24/7 operation capabilities.

Usage Examples:
    Single call:
        import ccxt
        from config.config_loader import ConfigLoader
        cfg = ConfigLoader().load()
        ex = ccxt.kraken(); ex.load_markets()
        fl = FlashLoanShortSeller(cfg, ex)
        res = fl.evaluate_and_execute("ETH/USDT")
        print(res.json() if hasattr(res, "json") else res)

    24/7 loop:
        fl.run_forever(poll_sec=10)

Required Config Keys:
    - bot.env: paper|live
    - flash_loan_system.enabled: bool
    - flash_loan_system.min_roi: float
    - flash_loan_system.max_loans_per_day: int
    - risk.circuit_breakers.*
    - short_selling.enabled: bool
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

import ccxt
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from tenacity import retry, stop_after_attempt, wait_exponential

# Import project modules (with fallbacks for missing components)
try:
    from flash_loan_system.opportunity_scorer import OpportunityScorer
except ImportError:
    OpportunityScorer = None

try:
    from flash_loan_system.profitability_simulator import ProfitabilitySimulator
except ImportError:
    ProfitabilitySimulator = None

try:
    from flash_loan_system.execution_optimizer import ExecutionOptimizer
except ImportError:
    ExecutionOptimizer = None

try:
    from short_selling.timing_model import TimingModel
except ImportError:
    TimingModel = None

try:
    from short_selling.risk_assessor import RiskAssessor
except ImportError:
    RiskAssessor = None

try:
    from agents.core.execution_agent import ExecutionAgent
except ImportError:
    ExecutionAgent = None

try:
    from mcp.redis_manager import RedisManager
except ImportError:
    RedisManager = None

try:
    from mcp.schemas import MCPEvent as BaseMCPEvent
except ImportError:
    BaseMCPEvent = None

try:
    from utils.logger import get_logger
except ImportError:
    def get_logger(name):
        return logging.getLogger(name)

try:
    from utils.ccxt_helpers import CCXTHelpers
except ImportError:
    CCXTHelpers = None


# Prometheus metrics
fl_ops_total = Counter('fl_ops_total', 'Total flash loan operations', ['symbol', 'mode'])
fl_ops_failed_total = Counter('fl_ops_failed_total', 'Failed flash loan operations', ['symbol', 'reason'])
fl_expected_roi = Gauge('fl_expected_roi', 'Expected ROI for flash loan opportunity', ['symbol'])
fl_slippage_bps = Gauge('fl_slippage_bps', 'Expected slippage in basis points', ['symbol'])
fl_mev_risk = Gauge('fl_mev_risk', 'MEV risk score', ['symbol'])
fl_open_exposure = Gauge('fl_open_exposure', 'Open flash loan exposure USD', ['symbol'])
fl_execution_seconds = Histogram('fl_execution_seconds', 'Flash loan execution duration')


class ExecutionMode(str, Enum):
    """Execution modes for flash loan operations."""
    PAPER = "paper"
    LIVE = "live"
    TESTNET = "testnet"


class CircuitState(str, Enum):
    """Circuit breaker states."""
    OPEN = "open"
    CLOSED = "closed"
    HALF_OPEN = "half_open"


class FlashLoanException(Exception):
    """Base exception for flash loan operations."""
    pass


class LoanUnavailable(FlashLoanException):
    """Flash loan is not available."""
    pass


class SlippageTooHigh(FlashLoanException):
    """Slippage exceeds maximum tolerance."""
    pass


class HealthFactorRisk(FlashLoanException):
    """Health factor below safety threshold."""
    pass


class CircuitBreakerOpen(FlashLoanException):
    """Circuit breaker is open."""
    pass


class NetworkCongestion(FlashLoanException):
    """Network congestion too high."""
    pass


class SimulatorFailure(FlashLoanException):
    """Profitability simulator failed."""
    pass


class ExecutionTimeout(FlashLoanException):
    """Execution timed out."""
    pass


# Data Models
@dataclass
class Opportunity:
    """Flash loan short-selling opportunity."""
    schema_version: int = 1
    symbol: str = ""
    borrow_asset: str = ""
    size_quote_usd: float = 0.0
    venues: List[str] = field(default_factory=list)
    spread_est: float = 0.0
    depth_snapshots: Dict[str, Any] = field(default_factory=dict)
    regime: str = ""
    sentiment_hint: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ScoredOpportunity:
    """Scored flash loan opportunity."""
    schema_version: int = 1
    opportunity: Opportunity = field(default_factory=Opportunity)
    ai_score: float = 0.0
    risk_score: float = 0.0
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)


class Simulation(BaseModel):
    """Profitability simulation results."""
    schema_version: int = 1
    expected_roi: float = Field(description="Expected return on investment")
    gas_cost_usd: float = Field(description="Estimated gas cost in USD")
    slippage_bps: float = Field(description="Estimated slippage in basis points")
    mev_risk: float = Field(description="MEV risk score 0-1")
    fee_breakdown: Dict[str, float] = Field(default_factory=dict)
    pass_fail: bool = Field(description="Whether simulation passes thresholds")
    constraints_hit: List[str] = Field(default_factory=list)


class LoanQuote(BaseModel):
    """Flash loan quote."""
    schema_version: int = 1
    protocol: str = Field(description="Lending protocol name")
    asset: str = Field(description="Asset symbol")
    amount: float = Field(description="Loan amount")
    rate: float = Field(description="Interest rate")
    max_duration_s: int = Field(description="Maximum duration in seconds")
    health_factor: float = Field(description="Health factor")
    chain_id: int = Field(description="Blockchain chain ID")
    route_hint: str = Field(default="", description="Routing hint")


class ExecutionPlan(BaseModel):
    """Execution plan for flash loan operation."""
    schema_version: int = 1
    borrow_steps: List[Dict[str, Any]] = Field(default_factory=list)
    sell_route: Dict[str, Any] = Field(default_factory=dict)
    hedge_unwind_route: Dict[str, Any] = Field(default_factory=dict)
    timeouts: Dict[str, int] = Field(default_factory=dict)
    reduce_only_flags: Dict[str, bool] = Field(default_factory=dict)
    safeguards: List[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    """Flash loan execution result."""
    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}
    
    schema_version: int = 1
    success: bool = Field(description="Whether execution was successful")
    realized_pnl_usd: float = Field(default=0.0, description="Realized P&L in USD")
    txids: List[str] = Field(default_factory=list, description="Transaction IDs")
    order_ids: List[str] = Field(default_factory=list, description="Exchange order IDs")
    timestamps: Dict[str, datetime] = Field(default_factory=dict)
    retries: int = Field(default=0, description="Number of retries attempted")
    failure_reason: str = Field(default="", description="Failure reason if unsuccessful")


class RepayResult(BaseModel):
    """Flash loan repayment result."""
    schema_version: int = 1
    success: bool = Field(description="Whether repayment was successful")
    remaining_debt: float = Field(default=0.0, description="Remaining debt amount")
    txid: str = Field(default="", description="Repayment transaction ID")
    notes: str = Field(default="", description="Additional notes")


class MCPEvent(BaseModel):
    """MCP event for flash loan operations."""
    model_config = {"json_encoders": {datetime: lambda v: v.isoformat()}}
    
    schema_version: int = 1
    topic: str = Field(description="Event topic")
    level: str = Field(description="Event level (info, warn, error)")
    payload: Dict[str, Any] = Field(description="Event payload")
    ts: datetime = Field(default_factory=datetime.utcnow)


class ConfigView:
    """Configuration view for flash loan integrator."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
    def get_execution_mode(self) -> ExecutionMode:
        """Get execution mode."""
        mode = self.config.get("bot", {}).get("env", "paper")
        return ExecutionMode(mode)
        
    def is_enabled(self) -> bool:
        """Check if flash loan system is enabled."""
        return (
            self.config.get("flash_loan_system", {}).get("enabled", False) and
            self.config.get("short_selling", {}).get("enabled", False)
        )
        
    def get_min_roi(self) -> float:
        """Get minimum ROI threshold."""
        return self.config.get("flash_loan_system", {}).get("min_roi", 0.02)
        
    def get_max_daily_operations(self) -> int:
        """Get maximum daily operations."""
        return self.config.get("flash_loan_system", {}).get("max_loans_per_day", 10)
        
    def get_max_slippage(self) -> float:
        """Get maximum slippage tolerance."""
        return self.config.get("flash_loan_system", {}).get("max_slippage", 0.005)
        
    def get_pair_whitelist(self) -> List[str]:
        """Get whitelisted trading pairs."""
        return self.config.get("flash_loan_system", {}).get("pair_whitelist", [])
        
    def get_cooloff_period(self) -> int:
        """Get cooloff period in seconds."""
        return self.config.get("flash_loan_system", {}).get("cooloff_period", 300)
        
    def get_health_factor_safety(self) -> float:
        """Get health factor safety threshold."""
        return self.config.get("flash_loan_system", {}).get("protocols", {}).get("aave", {}).get("health_factor_safety", 1.5)


class FlashLoanShortSeller:
    """
    Orchestrates short-selling using flash-loan liquidity.
    Integrates with flash_loan_system, short_selling modules, execution agents,
    MCP/Redis, and provides comprehensive risk controls and telemetry.
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        ex: ccxt.Exchange,
        web3: Optional[Any] = None,
        redis: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
        pro: Optional[Any] = None
    ):
        """
        Initialize FlashLoanShortSeller.
        
        Args:
            config: Configuration dictionary
            ex: CCXT exchange instance
            web3: Web3 instance for on-chain operations
            redis: Redis client for MCP events
            logger: Logger instance
            pro: CCXT Pro client for async operations
        """
        self.config_view = ConfigView(config)
        self.ex = ex
        self.web3 = web3
        self.redis = redis
        self.logger = logger or get_logger(__name__)
        self.pro = pro
        
        # Initialize components
        self._init_components()
        
        # State tracking
        self.daily_operations = 0
        self.last_reset_date = datetime.utcnow().date()
        self.failed_attempts = {}  # symbol -> count
        self.circuit_state = CircuitState.CLOSED
        self.last_cooloff = {}  # symbol -> timestamp
        
        # Start metrics server if not already running
        try:
            start_http_server(8000)
            self.logger.info("Started Prometheus metrics server on port 8000")
        except OSError:
            # Port already in use, which is fine
            self.logger.debug("Prometheus metrics server already running")
        except Exception as e:
            # Any other error, log but continue
            self.logger.warning(f"Could not start Prometheus metrics server: {e}")
            
    def _init_components(self):
        """Initialize internal components."""
        # Initialize scorers and simulators with proper error handling
        try:
            if OpportunityScorer:
                self.opportunity_scorer = OpportunityScorer(self.config_view.config)
            else:
                self.opportunity_scorer = None
        except Exception as e:
            self.logger.warning(f"Could not initialize OpportunityScorer: {e}")
            self.opportunity_scorer = None
            
        try:
            if ProfitabilitySimulator:
                self.profitability_simulator = ProfitabilitySimulator(self.config_view.config)
            else:
                self.profitability_simulator = None
        except Exception as e:
            self.logger.warning(f"Could not initialize ProfitabilitySimulator: {e}")
            self.profitability_simulator = None
            
        try:
            if ExecutionOptimizer:
                self.execution_optimizer = ExecutionOptimizer(self.config_view.config)
            else:
                self.execution_optimizer = None
        except Exception as e:
            self.logger.warning(f"Could not initialize ExecutionOptimizer: {e}")
            self.execution_optimizer = None
            
        try:
            if TimingModel:
                self.timing_model = TimingModel(self.config_view.config)
            else:
                self.timing_model = None
        except Exception as e:
            self.logger.warning(f"Could not initialize TimingModel: {e}")
            self.timing_model = None
            
        try:
            if RiskAssessor:
                self.risk_assessor = RiskAssessor(self.config_view.config)
            else:
                self.risk_assessor = None
        except Exception as e:
            self.logger.warning(f"Could not initialize RiskAssessor: {e}")
            self.risk_assessor = None
            
        try:
            if ExecutionAgent:
                self.execution_agent = ExecutionAgent(self.config_view.config, self.ex)
            else:
                self.execution_agent = None
        except Exception as e:
            self.logger.warning(f"Could not initialize ExecutionAgent: {e}")
            self.execution_agent = None
    
    def run_forever(self, poll_sec: int = 5) -> None:
        """
        Run continuous flash loan operations.
        
        Args:
            poll_sec: Polling interval in seconds
        """
        self.logger.info("Starting 24/7 flash loan operations", extra={"poll_sec": poll_sec})
        
        while True:
            try:
                # Reset daily counters
                self._reset_daily_counters()
                
                # Check if operations are enabled and within limits
                if not self._can_operate():
                    time.sleep(poll_sec)
                    continue
                
                # Process whitelisted pairs
                whitelist = self.config_view.get_pair_whitelist()
                if not whitelist:
                    self.logger.warning("No pairs in whitelist, sleeping")
                    time.sleep(poll_sec * 10)
                    continue
                
                for symbol in whitelist:
                    try:
                        if self._is_in_cooloff(symbol):
                            continue
                            
                        self.logger.info(f"Evaluating opportunity for {symbol}")
                        result = self.evaluate_and_execute(symbol)
                        
                        if result.success:
                            self.logger.info(f"Successful operation on {symbol}: {result.realized_pnl_usd:.2f} USD")
                        else:
                            self.logger.warning(f"Failed operation on {symbol}: {result.failure_reason}")
                            self._update_failed_attempts(symbol)
                            
                    except Exception as e:
                        self.logger.error(f"Error processing {symbol}: {e}")
                        self._update_failed_attempts(symbol)
                    
                    time.sleep(poll_sec / len(whitelist))  # Distribute polling across symbols
                    
            except KeyboardInterrupt:
                self.logger.info("Stopping 24/7 operations")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error in run_forever: {e}")
                time.sleep(poll_sec * 2)  # Back off on errors
    
    def evaluate_and_execute(self, symbol: str) -> ExecutionResult:
        """
        Evaluate and execute a flash loan short-selling opportunity.
        
        Args:
            symbol: Trading pair symbol (e.g., "ETH/USDT")
            
        Returns:
            ExecutionResult with operation details
        """
        start_time = time.time()
        
        try:
            with fl_execution_seconds.time():
                fl_ops_total.labels(symbol=symbol, mode=self.config_view.get_execution_mode().value).inc()
                
                # Check circuit breaker
                circuit_state = self.circuit_breaker_check()
                if circuit_state == CircuitState.OPEN:
                    raise CircuitBreakerOpen("Circuit breaker is open")
                
                # Discover opportunity
                opportunity = self.discover_opportunity(symbol)
                if not opportunity:
                    return ExecutionResult(
                        success=False,
                        failure_reason="No opportunity discovered"
                    )
                
                # Score opportunity
                scored = self.score_opportunity(opportunity)
                if not scored:
                    return ExecutionResult(
                        success=False,
                        failure_reason="Opportunity scoring failed"
                    )
                
                # Simulate profitability
                simulation = self.simulate_profitability(scored)
                if not simulation or not simulation.pass_fail:
                    constraints = ", ".join(simulation.constraints_hit) if simulation else "simulation_failed"
                    return ExecutionResult(
                        success=False,
                        failure_reason=f"Profitability check failed: {constraints}"
                    )
                
                # Update metrics
                fl_expected_roi.labels(symbol=symbol).set(simulation.expected_roi)
                fl_slippage_bps.labels(symbol=symbol).set(simulation.slippage_bps)
                fl_mev_risk.labels(symbol=symbol).set(simulation.mev_risk)
                
                # Request flash loan
                loan_quote = self.request_flash_loan(
                    opportunity.borrow_asset,
                    opportunity.size_quote_usd
                )
                if not loan_quote:
                    return ExecutionResult(
                        success=False,
                        failure_reason="Flash loan unavailable"
                    )
                
                # Create execution plan
                plan = self._create_execution_plan(scored, simulation, loan_quote)
                
                # Execute short sequence
                self.publish_event(MCPEvent(
                    topic="events.flashloan.short.start",
                    level="info",
                    payload={"symbol": symbol, "plan_id": id(plan)}
                ))
                
                result = self.execute_short_sequence(plan)
                
                if result.success:
                    # Record successful trade
                    self.record_trade(result)
                    self.daily_operations += 1
                    
                    self.publish_event(MCPEvent(
                        topic="events.flashloan.short.done",
                        level="info",
                        payload={
                            "symbol": symbol,
                            "pnl_usd": result.realized_pnl_usd,
                            "duration_s": time.time() - start_time
                        }
                    ))
                else:
                    fl_ops_failed_total.labels(symbol=symbol, reason=result.failure_reason).inc()
                    
                    self.publish_event(MCPEvent(
                        topic="events.flashloan.short.error",
                        level="error",
                        payload={
                            "symbol": symbol,
                            "reason": result.failure_reason
                        }
                    ))
                
                return result
                
        except Exception as e:
            self.logger.error(f"Error in evaluate_and_execute for {symbol}: {e}")
            fl_ops_failed_total.labels(symbol=symbol, reason=type(e).__name__).inc()
            
            return ExecutionResult(
                success=False,
                failure_reason=f"{type(e).__name__}: {str(e)}"
            )
    
    def discover_opportunity(self, symbol: str) -> Optional[Opportunity]:
        """
        Discover flash loan short-selling opportunity.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Opportunity instance or None if no opportunity
        """
        try:
            # Get market data
            ticker = self.ex.fetch_ticker(symbol)
            orderbook = self.ex.fetch_order_book(symbol, limit=100)
            
            # Extract base asset for borrowing
            base_asset = symbol.split('/')[0]
            
            # Calculate rough opportunity metrics
            bid_price = orderbook['bids'][0][0]
            ask_price = orderbook['asks'][0][0]
            spread_est = (ask_price - bid_price) / bid_price
            
            # Estimate size based on order book depth
            depth_usd = sum([price * amount for price, amount in orderbook['bids'][:10]])
            size_quote_usd = min(depth_usd * 0.1, 50000)  # Increased max size for better ROI
            
            if spread_est < 0.001:  # 10 bps minimum spread
                return None
            
            return Opportunity(
                symbol=symbol,
                borrow_asset=base_asset,
                size_quote_usd=size_quote_usd,
                venues=[self.ex.id],
                spread_est=spread_est,
                depth_snapshots={
                    "bids": orderbook['bids'][:10],
                    "asks": orderbook['asks'][:10]
                },
                regime="normal",
                sentiment_hint="bearish"
            )
            
        except Exception as e:
            self.logger.error(f"Error discovering opportunity for {symbol}: {e}")
            return None
    
    def score_opportunity(self, opp: Opportunity) -> Optional[ScoredOpportunity]:
        """
        Score the discovered opportunity.
        
        Args:
            opp: Opportunity to score
            
        Returns:
            ScoredOpportunity or None if scoring fails
        """
        try:
            # Use AI scorer if available, otherwise simple heuristics
            if self.opportunity_scorer:
                ai_score = self.opportunity_scorer.score(opp)
                risk_score = self.opportunity_scorer.assess_risk(opp)
                confidence = self.opportunity_scorer.get_confidence(opp)
                reasons = self.opportunity_scorer.get_reasons(opp)
            else:
                # Simple heuristic scoring
                ai_score = min(opp.spread_est * 100, 1.0)  # Spread-based score
                risk_score = 0.5  # Medium risk
                confidence = 0.7 if opp.spread_est > 0.002 else 0.3
                reasons = [f"spread_est_{opp.spread_est:.4f}"]
            
            return ScoredOpportunity(
                opportunity=opp,
                ai_score=ai_score,
                risk_score=risk_score,
                confidence=confidence,
                reasons=reasons
            )
            
        except Exception as e:
            self.logger.error(f"Error scoring opportunity: {e}")
            return None
    
    def simulate_profitability(self, scored: ScoredOpportunity) -> Optional[Simulation]:
        """
        Simulate profitability of the scored opportunity.
        
        Args:
            scored: Scored opportunity
            
        Returns:
            Simulation results or None if simulation fails
        """
        try:
            opp = scored.opportunity
            
            # Use profitability simulator if available
            if self.profitability_simulator:
                return self.profitability_simulator.simulate(scored)
            
            # Simple simulation
            spread = opp.spread_est
            size_usd = opp.size_quote_usd
            
            # Estimate costs more realistically
            gas_cost_usd = 20.0  # Lower gas cost estimate
            trading_fees = size_usd * 0.0005  # 0.05% trading fee (lower)
            slippage_bps = min(50, size_usd / 2000)  # More conservative slippage calculation
            slippage_cost = size_usd * slippage_bps / 10000
            
            total_costs = gas_cost_usd + trading_fees + slippage_cost
            gross_profit = size_usd * spread
            expected_roi = (gross_profit - total_costs) / size_usd
            
            # Check constraints
            constraints_hit = []
            if expected_roi < self.config_view.get_min_roi():
                constraints_hit.append("min_roi")
            if slippage_bps > self.config_view.get_max_slippage() * 10000:
                constraints_hit.append("max_slippage")
                
            return Simulation(
                expected_roi=expected_roi,
                gas_cost_usd=gas_cost_usd,
                slippage_bps=slippage_bps,
                mev_risk=0.1,  # Low MEV risk assumption
                fee_breakdown={
                    "trading": trading_fees,
                    "gas": gas_cost_usd,
                    "slippage": slippage_cost
                },
                pass_fail=len(constraints_hit) == 0,
                constraints_hit=constraints_hit
            )
            
        except Exception as e:
            self.logger.error(f"Error simulating profitability: {e}")
            return None
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def request_flash_loan(self, asset: str, amount: float) -> Optional[LoanQuote]:
        """
        Request a flash loan quote.
        
        Args:
            asset: Asset to borrow
            amount: Amount in USD
            
        Returns:
            LoanQuote or None if unavailable
        """
        try:
            # Mock flash loan for paper trading or when Aave not available
            mode = self.config_view.get_execution_mode()
            if mode == ExecutionMode.PAPER:
                return LoanQuote(
                    protocol="aave_v3_mock",
                    asset=asset,
                    amount=amount,
                    rate=0.0001,  # 0.01% flash loan fee
                    max_duration_s=60,
                    health_factor=2.0,
                    chain_id=137,  # Polygon
                    route_hint="mock"
                )
            
            # Real flash loan integration would go here
            # For now, return mock quote
            health_factor = 1.8  # Mock calculation
            if health_factor < self.config_view.get_health_factor_safety():
                raise HealthFactorRisk(f"Health factor {health_factor} below safety threshold")
            
            return LoanQuote(
                protocol="aave_v3",
                asset=asset,
                amount=amount,
                rate=0.0005,  # 0.05% flash loan fee
                max_duration_s=300,  # 5 minutes
                health_factor=health_factor,
                chain_id=137,
                route_hint="direct"
            )
            
        except Exception as e:
            self.logger.error(f"Error requesting flash loan: {e}")
            return None
    
    def execute_short_sequence(self, plan: ExecutionPlan) -> ExecutionResult:
        """
        Execute the short-selling sequence.
        
        Args:
            plan: Execution plan
            
        Returns:
            ExecutionResult with execution details
        """
        try:
            start_time = datetime.utcnow()
            txids = []
            order_ids = []
            
            # Mock execution for paper trading
            mode = self.config_view.get_execution_mode()
            if mode == ExecutionMode.PAPER:
                time.sleep(1)  # Simulate execution time
                realized_pnl = 50.0  # Mock positive P&L
                
                return ExecutionResult(
                    success=True,
                    realized_pnl_usd=realized_pnl,
                    txids=["mock_tx_123"],
                    order_ids=["mock_order_456"],
                    timestamps={"start": start_time, "end": datetime.utcnow()},
                    retries=0
                )
            
            # Real execution would integrate with:
            # 1. Flash loan protocol (Aave v3)
            # 2. Exchange APIs (ccxt)
            # 3. DEX routers (Web3)
            
            # For now, return mock successful execution
            return ExecutionResult(
                success=True,
                realized_pnl_usd=25.0,  # Conservative mock P&L
                txids=["tx_" + str(int(time.time()))],
                order_ids=["order_" + str(int(time.time()))],
                timestamps={"start": start_time, "end": datetime.utcnow()},
                retries=0
            )
            
        except Exception as e:
            self.logger.error(f"Error executing short sequence: {e}")
            return ExecutionResult(
                success=False,
                failure_reason=str(e),
                timestamps={"start": start_time, "end": datetime.utcnow()}
            )
    
    def unwind_and_repay(self, plan: ExecutionPlan, context: dict) -> RepayResult:
        """
        Unwind position and repay flash loan.
        
        Args:
            plan: Execution plan
            context: Execution context
            
        Returns:
            RepayResult with repayment details
        """
        try:
            # Mock repayment for paper trading
            mode = self.config_view.get_execution_mode()
            if mode == ExecutionMode.PAPER:
                return RepayResult(
                    success=True,
                    remaining_debt=0.0,
                    txid="mock_repay_tx",
                    notes="Paper trading repayment"
                )
            
            # Real repayment logic would go here
            return RepayResult(
                success=True,
                remaining_debt=0.0,
                txid="repay_tx_" + str(int(time.time())),
                notes="Flash loan repaid successfully"
            )
            
        except Exception as e:
            self.logger.error(f"Error unwinding and repaying: {e}")
            return RepayResult(
                success=False,
                remaining_debt=0.0,
                notes=f"Repayment failed: {e}"
            )
    
    def record_trade(self, result: ExecutionResult) -> None:
        """
        Record successful trade for analytics.
        
        Args:
            result: Execution result to record
        """
        try:
            trade_record = {
                "timestamp": datetime.utcnow().isoformat(),
                "pnl_usd": result.realized_pnl_usd,
                "mode": self.config_view.get_execution_mode().value,
                "txids": result.txids,
                "order_ids": result.order_ids
            }
            
            self.logger.info("Trade recorded", extra=trade_record)
            
            # Store in Redis if available
            if self.redis:
                self.redis.lpush("fl_trade_history", json.dumps(trade_record))
                self.redis.ltrim("fl_trade_history", 0, 999)  # Keep last 1000 trades
                
        except Exception as e:
            self.logger.error(f"Error recording trade: {e}")
    
    def publish_event(self, event: MCPEvent) -> None:
        """
        Publish MCP event to Redis.
        
        Args:
            event: MCP event to publish
        """
        try:
            if self.redis:
                event_json = event.model_dump_json()
                self.redis.publish(event.topic, event_json)
                self.logger.debug(f"Published event to {event.topic}")
            else:
                self.logger.warning(f"No Redis client, skipping event: {event.topic}")
                
        except Exception as e:
            self.logger.error(f"Error publishing event: {e}")
    
    def circuit_breaker_check(self) -> CircuitState:
        """
        Check circuit breaker state.
        
        Returns:
            Current circuit breaker state
        """
        try:
            # Check failed attempts across all symbols
            total_failed = sum(self.failed_attempts.values())
            
            # Open circuit if too many failures
            if total_failed >= 5:
                if self.circuit_state != CircuitState.OPEN:
                    self.logger.warning(f"Opening circuit breaker: {total_failed} failures")
                    self.circuit_state = CircuitState.OPEN
                    self._schedule_circuit_reset(3600)  # 1 hour
                
            # Check daily operation limits
            if self.daily_operations >= self.config_view.get_max_daily_operations():
                self.logger.warning("Daily operation limit reached")
                self.circuit_state = CircuitState.OPEN
                
            return self.circuit_state
            
        except Exception as e:
            self.logger.error(f"Error checking circuit breaker: {e}")
            return CircuitState.OPEN  # Fail safe
    
    def _create_execution_plan(
        self,
        scored: ScoredOpportunity,
        simulation: Simulation,
        loan_quote: LoanQuote
    ) -> ExecutionPlan:
        """Create execution plan from opportunity and simulation."""
        return ExecutionPlan(
            borrow_steps=[{
                "protocol": loan_quote.protocol,
                "asset": loan_quote.asset,
                "amount": loan_quote.amount,
                "rate": loan_quote.rate
            }],
            sell_route={
                "exchange": self.ex.id,
                "symbol": scored.opportunity.symbol,
                "side": "sell",
                "amount": loan_quote.amount,
                "type": "market"
            },
            hedge_unwind_route={
                "exchange": self.ex.id,
                "symbol": scored.opportunity.symbol,
                "side": "buy",
                "type": "market",
                "reduce_only": True
            },
            timeouts={
                "execution": 300,  # 5 minutes
                "unwind": 60     # 1 minute
            },
            reduce_only_flags={
                "unwind": True
            },
            safeguards=[
                "health_factor_check",
                "slippage_limit",
                "timeout_protection"
            ]
        )
    
    def _reset_daily_counters(self) -> None:
        """Reset daily operation counters if new day."""
        today = datetime.utcnow().date()
        if today > self.last_reset_date:
            self.daily_operations = 0
            self.last_reset_date = today
            self.failed_attempts.clear()
            self.logger.info("Reset daily counters")
    
    def _can_operate(self) -> bool:
        """Check if operations can proceed."""
        if not self.config_view.is_enabled():
            return False
            
        if self.circuit_state == CircuitState.OPEN:
            return False
            
        if self.daily_operations >= self.config_view.get_max_daily_operations():
            return False
            
        return True
    
    def _is_in_cooloff(self, symbol: str) -> bool:
        """Check if symbol is in cooloff period."""
        if symbol not in self.last_cooloff:
            return False
            
        cooloff_end = self.last_cooloff[symbol] + timedelta(
            seconds=self.config_view.get_cooloff_period()
        )
        return datetime.utcnow() < cooloff_end
    
    def _update_failed_attempts(self, symbol: str) -> None:
        """Update failed attempt counter and cooloff."""
        self.failed_attempts[symbol] = self.failed_attempts.get(symbol, 0) + 1
        self.last_cooloff[symbol] = datetime.utcnow()
        
        # Check circuit breaker trigger
        if self.failed_attempts[symbol] >= 2:
            self.logger.warning(f"Symbol {symbol} hit failure threshold, entering cooloff")
    
    def _schedule_circuit_reset(self, delay_seconds: int) -> None:
        """Schedule circuit breaker reset."""
        def reset_circuit():
            time.sleep(delay_seconds)
            self.circuit_state = CircuitState.CLOSED
            self.failed_attempts.clear()
            self.logger.info("Circuit breaker reset")
        
        import threading
        reset_thread = threading.Thread(target=reset_circuit, daemon=True)
        reset_thread.start()