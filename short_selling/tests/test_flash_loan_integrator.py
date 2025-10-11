"""
Test suite for FlashLoanShortSeller integration module.

Run with: pytest short_selling/tests/test_flash_loan_integrator.py -v
"""

import pytest
import time
import warnings
from datetime import datetime, timedelta
from unittest.mock import Mock
from collections import defaultdict, deque

# Suppress Pydantic warnings for cleaner test output
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydantic")

from short_selling.flash_loan_integrator import (
    FlashLoanShortSeller,
    Opportunity,
    ScoredOpportunity,
    ExecutionPlan,
    ExecutionResult,
    MCPEvent,
    ConfigView,
    ExecutionMode,
    CircuitState
)


# Mock Components for Testing
class MockExchange:
    """Mock CCXT exchange for testing."""
    
    def __init__(self, exchange_id: str = "mock_exchange"):
        self.id = exchange_id
        self.name = "Mock Exchange"
        self.markets = {}
        self.tickers = {}
        self.orderbooks = {}
        self.spreads = {}
        self._setup_default_markets()
        self._markets_loaded = False
        
    def _setup_default_markets(self):
        """Setup default market data."""
        pairs = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
        
        for pair in pairs:
            base, quote = pair.split('/')
            price = 45000.0 if base == "BTC" else 3000.0 if base == "ETH" else 300.0
            
            self.markets[pair] = {
                'symbol': pair,
                'base': base,
                'quote': quote,
                'active': True,
                'precision': {'amount': 8, 'price': 2},
                'limits': {'amount': {'min': 0.0001, 'max': 1000000}},
                'fees': {'trading': {'maker': 0.001, 'taker': 0.001}}
            }
            
            self.tickers[pair] = {
                'symbol': pair,
                'timestamp': int(time.time() * 1000),
                'bid': price * 0.999,
                'ask': price * 1.001,
                'last': price,
                'close': price,
                'baseVolume': 1000.0,
                'quoteVolume': 1000.0 * price
            }
            
            self.orderbooks[pair] = self._generate_orderbook(price)
            
    def _generate_orderbook(self, mid_price: float) -> dict:
        """Generate realistic order book."""
        # Generate tighter spread for better testing (default ~20 bps)
        spread_half = mid_price * 0.001  # 0.1% spread = 10 bps each side
        
        bids = []
        asks = []
        
        # Generate bids (buyers) below mid price
        for i in range(20):
            price = mid_price - spread_half - (i * mid_price * 0.0001)
            amount = 10.0 + i * 2.0
            bids.append([price, amount])
            
        # Generate asks (sellers) above mid price  
        for i in range(20):
            price = mid_price + spread_half + (i * mid_price * 0.0001)
            amount = 10.0 + i * 2.0
            asks.append([price, amount])
        
        return {
            'bids': bids,
            'asks': asks,
            'timestamp': int(time.time() * 1000)
        }
        
    def load_markets(self, reload: bool = False) -> dict:
        """Simulate market loading."""
        time.sleep(0.01)
        self._markets_loaded = True
        return self.markets
        
    def fetch_ticker(self, symbol: str) -> dict:
        """Fetch ticker for symbol."""
        if symbol not in self.tickers:
            raise Exception(f"Market {symbol} not found")
        return self.tickers[symbol].copy()
        
    def fetch_order_book(self, symbol: str, limit: int = None) -> dict:
        """Fetch order book for symbol."""
        if symbol not in self.orderbooks:
            raise Exception(f"Market {symbol} not found")
            
        orderbook = self.orderbooks[symbol].copy()
        orderbook['symbol'] = symbol
        
        # Apply custom spread if set
        if symbol in self.spreads:
            mid_price = (orderbook['bids'][0][0] + orderbook['asks'][0][0]) / 2
            spread = self.spreads[symbol]
            orderbook['bids'][0][0] = mid_price * (1 - spread / 2)
            orderbook['asks'][0][0] = mid_price * (1 + spread / 2)
            
        if limit:
            orderbook['bids'] = orderbook['bids'][:limit]
            orderbook['asks'] = orderbook['asks'][:limit]
            
        return orderbook
        
    def set_spread(self, symbol: str, spread: float) -> None:
        """Set custom spread for testing."""
        self.spreads[symbol] = spread


class MockRedis:
    """Mock Redis client for testing."""
    
    def __init__(self):
        self._data = {}
        self._lists = defaultdict(deque)
        self._published_messages = []
        
        # Mock methods
        self.lpush = Mock(side_effect=self._lpush)
        self.ltrim = Mock(side_effect=self._ltrim)
        self.publish = Mock(side_effect=self._publish)
        self.get = Mock(side_effect=self._get)
        self.set = Mock(side_effect=self._set)
        
    def _lpush(self, key: str, *values) -> int:
        """Left push to list."""
        for value in reversed(values):
            self._lists[key].appendleft(value)
        return len(self._lists[key])
        
    def _ltrim(self, key: str, start: int, end: int) -> bool:
        """Trim list to range."""
        if key in self._lists:
            items = list(self._lists[key])
            self._lists[key] = deque(items[start:end+1] if end != -1 else items[start:])
        return True
        
    def _publish(self, channel: str, message: str) -> int:
        """Publish message to channel."""
        self._published_messages.append({'channel': channel, 'message': message})
        return 1
        
    def _get(self, key: str) -> str:
        """Get value by key."""
        return self._data.get(key)
        
    def _set(self, key: str, value) -> bool:
        """Set key-value pair."""
        self._data[key] = str(value)
        return True


# Test Fixtures
@pytest.fixture
def sample_config():
    """Sample configuration for testing."""
    return {
        "bot": {"env": "paper"},
        "flash_loan_system": {
            "enabled": True,
            "min_roi": 0.02,
            "max_loans_per_day": 10,
            "max_slippage": 0.005,
            "pair_whitelist": ["BTC/USDT", "ETH/USDT"],
            "cooloff_period": 300,
            "protocols": {"aave": {"health_factor_safety": 1.5}}
        },
        "short_selling": {
            "enabled": True,
            "max_short_duration": 3600
        },
        "risk": {
            "circuit_breakers": {"max_failures": 5}
        }
    }


@pytest.fixture
def mock_exchange():
    """Mock CCXT exchange for testing."""
    return MockExchange()


@pytest.fixture
def mock_redis():
    """Mock Redis client for testing."""
    return MockRedis()


@pytest.fixture
def mock_logger():
    """Mock logger for testing."""
    return Mock()


@pytest.fixture
def flash_loan_seller(sample_config, mock_exchange, mock_redis, mock_logger):
    """FlashLoanShortSeller instance for testing."""
    return FlashLoanShortSeller(
        config=sample_config,
        ex=mock_exchange,
        redis=mock_redis,
        logger=mock_logger
    )


# Test Classes
class TestConfigView:
    """Test ConfigView functionality."""
    
    def test_config_view_initialization(self, sample_config):
        """Test proper initialization."""
        config_view = ConfigView(sample_config)
        assert config_view.get_execution_mode() == ExecutionMode.PAPER
        assert config_view.is_enabled() is True
        assert config_view.get_min_roi() == 0.02
        assert config_view.get_max_daily_operations() == 10
        
    def test_config_view_disabled(self, sample_config):
        """Test disabled configuration."""
        sample_config["flash_loan_system"]["enabled"] = False
        config_view = ConfigView(sample_config)
        assert config_view.is_enabled() is False
        
    def test_config_view_defaults(self):
        """Test default values."""
        config_view = ConfigView({})
        assert config_view.get_execution_mode() == ExecutionMode.PAPER
        assert config_view.is_enabled() is False
        assert config_view.get_min_roi() == 0.02


class TestFlashLoanShortSeller:
    """Test FlashLoanShortSeller main functionality."""
    
    def test_initialization(self, flash_loan_seller):
        """Test proper initialization."""
        assert flash_loan_seller.config_view is not None
        assert flash_loan_seller.daily_operations == 0
        assert flash_loan_seller.circuit_state == CircuitState.CLOSED
        
    def test_discover_opportunity_success(self, flash_loan_seller):
        """Test successful opportunity discovery."""
        opportunity = flash_loan_seller.discover_opportunity("BTC/USDT")
        
        assert opportunity is not None
        assert opportunity.symbol == "BTC/USDT"
        assert opportunity.borrow_asset == "BTC"
        assert opportunity.size_quote_usd > 0
        assert opportunity.spread_est > 0
        
    def test_discover_opportunity_low_spread(self, flash_loan_seller, mock_exchange):
        """Test opportunity discovery with low spread."""
        mock_exchange.set_spread("BTC/USDT", 0.0005)  # 5 bps
        
        opportunity = flash_loan_seller.discover_opportunity("BTC/USDT")
        assert opportunity is None  # Should reject low spread
        
    def test_score_opportunity(self, flash_loan_seller):
        """Test opportunity scoring."""
        opportunity = Opportunity(
            symbol="BTC/USDT",
            borrow_asset="BTC",
            size_quote_usd=1000.0,
            spread_est=0.003,
            venues=["test"]
        )
        
        scored = flash_loan_seller.score_opportunity(opportunity)
        
        assert scored is not None
        assert scored.ai_score > 0
        assert scored.risk_score >= 0
        assert scored.confidence > 0
        assert len(scored.reasons) > 0
        
    def test_simulate_profitability_pass(self, flash_loan_seller):
        """Test profitability simulation that passes."""
        opportunity = Opportunity(
            symbol="BTC/USDT",
            borrow_asset="BTC",
            size_quote_usd=50000.0,  # Large size for good ROI
            spread_est=0.008  # 80 bps spread - much higher
        )
        scored = ScoredOpportunity(
            opportunity=opportunity,
            ai_score=0.8,
            risk_score=0.3,
            confidence=0.9
        )
        
        simulation = flash_loan_seller.simulate_profitability(scored)
        
        assert simulation is not None
        # Calculate expected ROI manually for verification
        gross_profit = 50000.0 * 0.008  # $400
        trading_fees = 50000.0 * 0.0005  # $25
        gas_cost = 20.0
        slippage_cost = 50000.0 * (50000.0/2000/10000)  # ~$62.5
        total_costs = trading_fees + gas_cost + slippage_cost  # ~$107.5
        expected_roi = (gross_profit - total_costs) / 50000.0  # Should be ~0.058 (5.8%)
        
        print(f"Debug: Expected ROI = {simulation.expected_roi:.4f}, Required = 0.02")
        assert simulation.expected_roi >= 0.02  # Above min ROI
        assert simulation.pass_fail is True
        assert len(simulation.constraints_hit) == 0
        
    def test_simulate_profitability_fail_roi(self, flash_loan_seller):
        """Test profitability simulation that fails on ROI."""
        opportunity = Opportunity(
            symbol="BTC/USDT",
            borrow_asset="BTC",
            size_quote_usd=1000.0,  # Small size
            spread_est=0.001  # Low spread
        )
        scored = ScoredOpportunity(
            opportunity=opportunity,
            ai_score=0.3,
            risk_score=0.7,
            confidence=0.5
        )
        
        simulation = flash_loan_seller.simulate_profitability(scored)
        
        assert simulation is not None
        assert simulation.expected_roi < 0.02
        assert simulation.pass_fail is False
        assert "min_roi" in simulation.constraints_hit
        
    def test_request_flash_loan_paper_mode(self, flash_loan_seller):
        """Test flash loan request in paper mode."""
        quote = flash_loan_seller.request_flash_loan("BTC", 1000.0)
        
        assert quote is not None
        assert quote.protocol == "aave_v3_mock"
        assert quote.asset == "BTC"
        assert quote.amount == 1000.0
        assert quote.rate == 0.0001
        
    def test_execute_short_sequence_paper_mode(self, flash_loan_seller):
        """Test short sequence execution in paper mode."""
        plan = ExecutionPlan(
            borrow_steps=[{"asset": "BTC", "amount": 1000.0}],
            sell_route={"exchange": "test", "symbol": "BTC/USDT"},
            timeouts={"execution": 300}
        )
        
        result = flash_loan_seller.execute_short_sequence(plan)
        
        assert result.success is True
        assert result.realized_pnl_usd > 0
        assert len(result.txids) > 0
        assert len(result.order_ids) > 0
        
    def test_evaluate_and_execute_success(self, flash_loan_seller):
        """Test successful end-to-end execution."""
        result = flash_loan_seller.evaluate_and_execute("BTC/USDT")
        
        assert result.success is True
        assert result.realized_pnl_usd > 0
        assert flash_loan_seller.daily_operations == 1
        
    def test_evaluate_and_execute_no_opportunity(self, flash_loan_seller, mock_exchange):
        """Test execution when no opportunity exists."""
        mock_exchange.set_spread("BTC/USDT", 0.0001)
        
        result = flash_loan_seller.evaluate_and_execute("BTC/USDT")
        
        assert result.success is False
        assert "No opportunity discovered" in result.failure_reason
        
    def test_circuit_breaker_functionality(self, flash_loan_seller):
        """Test circuit breaker opens after failures."""
        # Simulate multiple failures
        for i in range(5):
            flash_loan_seller._update_failed_attempts("BTC/USDT")
            
        state = flash_loan_seller.circuit_breaker_check()
        assert state == CircuitState.OPEN
        
        # Should prevent execution
        result = flash_loan_seller.evaluate_and_execute("BTC/USDT")
        assert result.success is False
        assert "CircuitBreakerOpen" in result.failure_reason
            
    def test_daily_operation_limits(self, flash_loan_seller):
        """Test daily operation limits are enforced."""
        flash_loan_seller.daily_operations = 10
        
        state = flash_loan_seller.circuit_breaker_check()
        assert state == CircuitState.OPEN
        
        assert not flash_loan_seller._can_operate()
        
    def test_cooloff_period(self, flash_loan_seller):
        """Test cooloff period enforcement."""
        symbol = "BTC/USDT"
        
        # Trigger cooloff
        flash_loan_seller._update_failed_attempts(symbol)
        flash_loan_seller._update_failed_attempts(symbol)
        
        # Should be in cooloff
        assert flash_loan_seller._is_in_cooloff(symbol)
        
        # Simulate time passage
        flash_loan_seller.last_cooloff[symbol] = datetime.utcnow() - timedelta(seconds=400)
        
        # Should no longer be in cooloff
        assert not flash_loan_seller._is_in_cooloff(symbol)
        
    def test_record_trade(self, flash_loan_seller, mock_redis):
        """Test trade recording functionality."""
        result = ExecutionResult(
            success=True,
            realized_pnl_usd=100.0,
            txids=["tx123"],
            order_ids=["order456"]
        )
        
        flash_loan_seller.record_trade(result)
        
        # Check Redis was called
        assert mock_redis.lpush.called
        assert mock_redis.ltrim.called
        
    def test_publish_event(self, flash_loan_seller, mock_redis):
        """Test MCP event publishing."""
        event = MCPEvent(
            topic="test.topic",
            level="info",
            payload={"test": "data"}
        )
        
        flash_loan_seller.publish_event(event)
        
        # Check Redis publish was called
        assert mock_redis.publish.called


class TestRiskControls:
    """Test risk control mechanisms."""
    
    def test_slippage_limits(self, flash_loan_seller):
        """Test slippage limit enforcement."""
        opportunity = Opportunity(
            symbol="BTC/USDT",
            borrow_asset="BTC",
            size_quote_usd=100000.0,  # Very large size
            spread_est=0.002
        )
        scored = ScoredOpportunity(
            opportunity=opportunity,
            ai_score=0.8,
            risk_score=0.2,
            confidence=0.9
        )
        
        simulation = flash_loan_seller.simulate_profitability(scored)
        
        # Should fail due to high slippage
        assert simulation.pass_fail is False
        assert "max_slippage" in simulation.constraints_hit


class TestDataModels:
    """Test data model functionality."""
    
    def test_opportunity_model(self):
        """Test Opportunity data model."""
        opp = Opportunity(
            symbol="BTC/USDT",
            borrow_asset="BTC",
            size_quote_usd=1000.0,
            spread_est=0.003
        )
        
        assert opp.symbol == "BTC/USDT"
        assert opp.schema_version == 1
        assert isinstance(opp.timestamp, datetime)
        
    def test_execution_result_model(self):
        """Test ExecutionResult data model."""
        result = ExecutionResult(
            success=True,
            realized_pnl_usd=50.0,
            txids=["tx1", "tx2"]
        )
        
        assert result.success is True
        assert result.realized_pnl_usd == 50.0
        assert len(result.txids) == 2
        
        # Test JSON serialization
        json_str = result.model_dump_json()
        assert "success" in json_str
        assert "realized_pnl_usd" in json_str
        
    def test_mcp_event_model(self):
        """Test MCPEvent data model."""
        event = MCPEvent(
            topic="test.topic",
            level="info",
            payload={"key": "value"}
        )
        
        assert event.topic == "test.topic"
        assert event.level == "info"
        assert event.payload["key"] == "value"
        assert isinstance(event.ts, datetime)
        
        # Test JSON serialization
        json_str = event.model_dump_json()
        assert "topic" in json_str
        assert "ts" in json_str


class TestIntegration:
    """Integration tests."""
    
    def test_full_workflow_integration(self, flash_loan_seller):
        """Test complete workflow integration."""
        result = flash_loan_seller.evaluate_and_execute("BTC/USDT")
        
        # Should complete successfully in paper mode
        assert result.success is True
        assert result.realized_pnl_usd > 0
        assert len(result.txids) > 0
        assert flash_loan_seller.daily_operations == 1
        
    def test_redis_integration(self, flash_loan_seller, mock_redis):
        """Test Redis integration."""
        result = flash_loan_seller.evaluate_and_execute("BTC/USDT")
        
        # Should have published events and recorded trade
        assert mock_redis.publish.call_count >= 1  # At least done event
        assert mock_redis.lpush.called  # Trade recording


if __name__ == "__main__":
    pytest.main([__file__, "-v"])