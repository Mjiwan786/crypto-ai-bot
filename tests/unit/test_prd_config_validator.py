"""
Unit tests for PRD-001 Section 7.3 Configuration Validation

Tests coverage:
- Pydantic model validation for all config sections
- Type checking (int, float, str, bool, enum)
- Range validation (min/max values)
- Required field validation
- Valid and invalid configurations

Author: Crypto AI Bot Team
"""

import pytest
import os
from config.prd_config_validator import (
    ConfigValidator,
    CryptoAIBotConfig,
    RedisConfig,
    ExchangeConfig,
    RiskConfig,
    PortfolioRiskConfig,
    NotionalLimitsConfig,
    ComplianceConfig,
    StrategyAllocation,
    TradingMode,
    LogLevel,
    get_validator
)


class TestRedisConfig:
    """Test Redis configuration validation."""

    def test_valid_redis_config(self):
        """Test valid Redis configuration."""
        config = RedisConfig(
            url="redis://localhost:6379",
            db=0,
            client_name="test-bot"
        )

        assert config.url == "redis://localhost:6379"
        assert config.db == 0
        assert config.client_name == "test-bot"

    def test_redis_url_required(self):
        """Test that Redis URL is required."""
        with pytest.raises(ValueError, match="Redis URL is required"):
            RedisConfig(url="")

    def test_redis_url_format_validation(self):
        """Test Redis URL format validation."""
        with pytest.raises(ValueError, match="must start with redis"):
            RedisConfig(url="http://localhost:6379")

    def test_redis_ssl_url(self):
        """Test Redis SSL URL is valid."""
        config = RedisConfig(url="rediss://localhost:6379")
        assert config.url == "rediss://localhost:6379"

    def test_redis_db_range_validation(self):
        """Test Redis DB range validation."""
        # Valid range [0, 15]
        config = RedisConfig(url="redis://localhost", db=15)
        assert config.db == 15

        # Invalid: too high
        with pytest.raises(ValueError):
            RedisConfig(url="redis://localhost", db=16)

        # Invalid: negative
        with pytest.raises(ValueError):
            RedisConfig(url="redis://localhost", db=-1)


class TestExchangeConfig:
    """Test Exchange configuration validation."""

    def test_valid_exchange_config(self):
        """Test valid exchange configuration."""
        config = ExchangeConfig(
            primary="kraken",
            api_key="test_key",
            api_secret="test_secret"
        )

        assert config.primary == "kraken"
        assert config.api_key == "test_key"

    def test_exchange_credentials_required_for_live_mode(self):
        """Test that credentials are required for live mode."""
        os.environ['TRADING_MODE'] = 'live'

        try:
            with pytest.raises(ValueError, match="API credentials.*required for live mode"):
                ExchangeConfig(primary="kraken")
        finally:
            os.environ['TRADING_MODE'] = 'paper'

    def test_exchange_credentials_optional_for_paper_mode(self):
        """Test that credentials are optional for paper mode."""
        os.environ['TRADING_MODE'] = 'paper'

        config = ExchangeConfig(primary="kraken")
        assert config.api_key is None
        assert config.api_secret is None

    def test_rate_limit_range_validation(self):
        """Test rate limit range validation."""
        # Valid
        config = ExchangeConfig(primary="kraken", requests_per_minute=100)
        assert config.requests_per_minute == 100

        # Too low
        with pytest.raises(ValueError):
            ExchangeConfig(primary="kraken", requests_per_minute=0)

        # Too high
        with pytest.raises(ValueError):
            ExchangeConfig(primary="kraken", requests_per_minute=2000)


class TestPortfolioRiskConfig:
    """Test portfolio risk configuration validation."""

    def test_valid_portfolio_risk_config(self):
        """Test valid portfolio risk configuration."""
        config = PortfolioRiskConfig(
            max_drawdown_pct=15.0,
            max_single_position_notional_usd=10000,
            max_total_exposure_usd=50000,
            max_concurrent_positions=10
        )

        assert config.max_drawdown_pct == 15.0
        assert config.max_single_position_notional_usd == 10000

    def test_drawdown_pct_range_validation(self):
        """Test drawdown percentage range validation."""
        # Valid range [1.0, 50.0]
        config = PortfolioRiskConfig(max_drawdown_pct=15.0)
        assert config.max_drawdown_pct == 15.0

        # Too low
        with pytest.raises(ValueError):
            PortfolioRiskConfig(max_drawdown_pct=0.5)

        # Too high
        with pytest.raises(ValueError):
            PortfolioRiskConfig(max_drawdown_pct=60.0)

    def test_position_limits_validation(self):
        """Test position limits validation."""
        # Valid
        config = PortfolioRiskConfig(max_single_position_notional_usd=5000)
        assert config.max_single_position_notional_usd == 5000

        # Too low
        with pytest.raises(ValueError):
            PortfolioRiskConfig(max_single_position_notional_usd=50)


class TestNotionalLimitsConfig:
    """Test notional limits configuration validation."""

    def test_valid_notional_limits(self):
        """Test valid notional limits."""
        config = NotionalLimitsConfig(min_usd=10.0, max_usd=10000.0)

        assert config.min_usd == 10.0
        assert config.max_usd == 10000.0

    def test_min_less_than_max_validation(self):
        """Test that min must be less than max."""
        with pytest.raises(ValueError, match="min_usd.*must be less than max_usd"):
            NotionalLimitsConfig(min_usd=10000.0, max_usd=10.0)

    def test_equal_min_max_fails(self):
        """Test that min == max fails."""
        with pytest.raises(ValueError):
            NotionalLimitsConfig(min_usd=100.0, max_usd=100.0)


class TestComplianceConfig:
    """Test compliance configuration validation."""

    def test_valid_compliance_config(self):
        """Test valid compliance configuration."""
        config = ComplianceConfig(
            kill_switch=False,
            allowed_symbols=["BTC/USD", "ETH/USD"],
            banned_symbols=[],
            quote_currencies_allowed=["USD"]
        )

        assert config.kill_switch is False
        assert len(config.allowed_symbols) == 2

    def test_allowed_symbols_required(self):
        """Test that at least one allowed symbol is required."""
        with pytest.raises(ValueError, match="At least one allowed symbol is required"):
            ComplianceConfig(allowed_symbols=[])

    def test_symbol_format_validation(self):
        """Test symbol format validation."""
        with pytest.raises(ValueError, match="Invalid symbol format"):
            ComplianceConfig(allowed_symbols=["BTCUSD"])  # Missing /


class TestStrategyAllocation:
    """Test strategy allocation validation."""

    def test_valid_strategy_allocation(self):
        """Test valid strategy allocation."""
        config = StrategyAllocation(
            scalper=0.4,
            trend=0.3,
            mean_reversion=0.2,
            breakout=0.1
        )

        assert config.scalper == 0.4
        assert config.trend == 0.3

    def test_allocations_sum_to_one(self):
        """Test that allocations must sum to 1.0."""
        # Valid: sums to 1.0
        config = StrategyAllocation(
            scalper=0.25,
            trend=0.25,
            mean_reversion=0.25,
            breakout=0.25
        )
        assert config.scalper == 0.25

        # Invalid: sums to less than 1.0
        with pytest.raises(ValueError, match="must sum to 1.0"):
            StrategyAllocation(
                scalper=0.2,
                trend=0.2,
                mean_reversion=0.2,
                breakout=0.2
            )

        # Invalid: sums to more than 1.0
        with pytest.raises(ValueError, match="must sum to 1.0"):
            StrategyAllocation(
                scalper=0.5,
                trend=0.5,
                mean_reversion=0.5,
                breakout=0.5
            )

    def test_allocation_range_validation(self):
        """Test allocation range validation [0, 1]."""
        # Too low
        with pytest.raises(ValueError):
            StrategyAllocation(
                scalper=-0.1,
                trend=0.3,
                mean_reversion=0.3,
                breakout=0.5
            )

        # Too high
        with pytest.raises(ValueError):
            StrategyAllocation(
                scalper=1.5,
                trend=0.0,
                mean_reversion=0.0,
                breakout=0.0
            )


class TestConfigValidator:
    """Test ConfigValidator class."""

    def test_validator_initialization(self):
        """Test validator initialization."""
        validator = ConfigValidator()
        assert validator is not None

    def test_validate_valid_config(self):
        """Test validation of valid configuration."""
        validator = ConfigValidator()

        config = {
            "redis": {
                "url": "redis://localhost:6379",
                "db": 0
            },
            "exchange": {
                "primary": "kraken"
            },
            "risk": {
                "portfolio": {
                    "max_drawdown_pct": 15.0
                }
            }
        }

        validated = validator.validate(config)
        assert isinstance(validated, CryptoAIBotConfig)
        assert validated.redis.url == "redis://localhost:6379"

    def test_validate_invalid_config_raises_error(self):
        """Test that invalid config raises ValueError."""
        validator = ConfigValidator()

        config = {
            "redis": {
                "url": ""  # Invalid: empty URL
            }
        }

        with pytest.raises(ValueError, match="Invalid configuration"):
            validator.validate(config)

    def test_validate_missing_required_field(self):
        """Test that missing required field raises error."""
        validator = ConfigValidator()

        config = {
            # Missing required 'redis' section
            "exchange": {
                "primary": "kraken"
            }
        }

        with pytest.raises(ValueError):
            validator.validate(config)


class TestFullConfiguration:
    """Test full configuration validation."""

    def test_complete_valid_configuration(self):
        """Test complete valid configuration."""
        config = {
            "mode": {
                "bot_mode": "PAPER",
                "enable_trading": False,
                "live_trading_confirmation": ""
            },
            "logging": {
                "level": "INFO",
                "dir": "logs/"
            },
            "redis": {
                "url": "redis://localhost:6379",
                "db": 0,
                "client_name": "crypto-ai-bot",
                "decode_responses": True
            },
            "exchange": {
                "primary": "kraken"
            },
            "risk": {
                "portfolio": {
                    "max_drawdown_pct": 15.0,
                    "max_single_position_notional_usd": 10000
                },
                "notional_limits": {
                    "min_usd": 10.0,
                    "max_usd": 10000.0
                },
                "compliance": {
                    "kill_switch": False,
                    "allowed_symbols": ["BTC/USD", "ETH/USD"]
                }
            },
            "strategies": {
                "allocations": {
                    "scalper": 0.4,
                    "trend": 0.3,
                    "mean_reversion": 0.2,
                    "breakout": 0.1
                }
            },
            "monitoring": {
                "prometheus": {
                    "enabled": True,
                    "port": 9108
                }
            }
        }

        validator = ConfigValidator()
        validated = validator.validate(config)

        assert validated.mode.bot_mode == "PAPER"
        assert validated.redis.url == "redis://localhost:6379"
        assert validated.risk.portfolio.max_drawdown_pct == 15.0
        assert validated.strategies.allocations.scalper == 0.4


class TestSingletonInstance:
    """Test singleton instance."""

    def test_get_validator_singleton(self):
        """Test that get_validator returns singleton."""
        validator1 = get_validator()
        validator2 = get_validator()

        assert validator1 is validator2
