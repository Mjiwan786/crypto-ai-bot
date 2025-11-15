"""
PRD-001 Section 7.3 Configuration Validation

This module implements PRD-001 Section 7.3 validation requirements with:
- Pydantic models for all config sections
- Validate config on load with Pydantic (fail fast)
- Type checking (int, float, str, bool, enum)
- Range validation (min/max values for numeric fields)
- Required field validation
- Comprehensive error messages

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import os
import logging
from typing import Dict, List, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict

logger = logging.getLogger(__name__)


# PRD-001 Section 7.3: Enums for config values
class TradingMode(str, Enum):
    """Trading mode enum."""
    PAPER = "paper"
    LIVE = "live"


class LogLevel(str, Enum):
    """Log level enum."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ExchangeName(str, Enum):
    """Exchange name enum."""
    KRAKEN = "kraken"
    KUCOIN = "kucoin"
    BINANCE = "binance"


# PRD-001 Section 7.3: Pydantic models for config sections
class RedisConfig(BaseModel):
    """Redis configuration validation."""
    model_config = ConfigDict(extra='allow')

    url: str = Field(..., description="Redis connection URL (required)")
    db: int = Field(default=0, ge=0, le=15, description="Redis database number")
    client_name: str = Field(default="crypto-ai-bot", description="Redis client name")
    decode_responses: bool = Field(default=True, description="Decode responses to strings")

    # Stream configuration
    streams: Dict[str, str] = Field(
        default_factory=lambda: {
            "md_trades": "md:trades",
            "md_spread": "md:spread",
            "md_book": "md:orderbook",
            "md_candles": "md:candles",
            "signals_paper": "signals:paper",
            "signals_live": "signals:live",
            "events": "events:bus"
        },
        description="Redis stream names"
    )

    @field_validator('url')
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate Redis URL format."""
        if not v:
            raise ValueError("Redis URL is required")

        if not (v.startswith('redis://') or v.startswith('rediss://')):
            raise ValueError("Redis URL must start with redis:// or rediss://")

        return v


class ExchangeConfig(BaseModel):
    """Exchange configuration validation."""
    model_config = ConfigDict(extra='allow')

    primary: ExchangeName = Field(
        default=ExchangeName.KRAKEN,
        description="Primary exchange"
    )

    # API credentials (optional, required for live mode)
    api_key: Optional[str] = Field(default=None, description="Exchange API key")
    api_secret: Optional[str] = Field(default=None, description="Exchange API secret")

    # Rate limiting
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    requests_per_minute: int = Field(
        default=60,
        ge=1,
        le=1000,
        description="Max requests per minute"
    )

    @model_validator(mode='after')
    def validate_live_mode_credentials(self) -> 'ExchangeConfig':
        """Validate that credentials are present for live mode."""
        # Check TRADING_MODE from environment
        trading_mode = os.getenv('TRADING_MODE', 'paper')

        if trading_mode == 'live':
            if not self.api_key or not self.api_secret:
                raise ValueError(
                    "Exchange API credentials (api_key and api_secret) are required for live mode"
                )

        return self


class PortfolioRiskConfig(BaseModel):
    """Portfolio risk limits validation."""
    model_config = ConfigDict(extra='allow')

    # PRD-001 Section 4.3: Drawdown limits
    max_drawdown_pct: float = Field(
        default=15.0,
        ge=1.0,
        le=50.0,
        description="Maximum portfolio drawdown % (PRD-001 Section 4.3)"
    )

    # Position limits
    max_single_position_notional_usd: float = Field(
        default=10000,
        ge=100,
        le=1000000,
        description="Maximum single position size in USD"
    )

    max_total_exposure_usd: float = Field(
        default=50000,
        ge=1000,
        le=10000000,
        description="Maximum total exposure in USD"
    )

    max_concurrent_positions: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of concurrent positions"
    )


class NotionalLimitsConfig(BaseModel):
    """Notional limits validation."""
    model_config = ConfigDict(extra='allow')

    min_usd: float = Field(
        default=10.0,
        ge=1.0,
        le=10000.0,
        description="Minimum position size in USD"
    )

    max_usd: float = Field(
        default=10000.0,
        ge=10.0,
        le=1000000.0,
        description="Maximum position size in USD"
    )

    @model_validator(mode='after')
    def validate_min_max(self) -> 'NotionalLimitsConfig':
        """Validate min < max."""
        if self.min_usd >= self.max_usd:
            raise ValueError(f"min_usd ({self.min_usd}) must be less than max_usd ({self.max_usd})")
        return self


class ComplianceConfig(BaseModel):
    """Compliance configuration validation."""
    model_config = ConfigDict(extra='allow')

    kill_switch: bool = Field(default=False, description="Global kill switch")

    allowed_symbols: List[str] = Field(
        default=["BTC/USD", "ETH/USD"],
        description="List of allowed trading symbols"
    )

    banned_symbols: List[str] = Field(
        default=[],
        description="List of banned trading symbols"
    )

    quote_currencies_allowed: List[str] = Field(
        default=["USD"],
        description="List of allowed quote currencies"
    )

    @field_validator('allowed_symbols')
    @classmethod
    def validate_allowed_symbols(cls, v: List[str]) -> List[str]:
        """Validate allowed symbols format."""
        if not v:
            raise ValueError("At least one allowed symbol is required")

        for symbol in v:
            if '/' not in symbol:
                raise ValueError(f"Invalid symbol format: {symbol}. Expected format: BASE/QUOTE")

        return v


class RiskConfig(BaseModel):
    """Overall risk configuration validation."""
    model_config = ConfigDict(extra='allow')

    portfolio: PortfolioRiskConfig = Field(
        default_factory=PortfolioRiskConfig,
        description="Portfolio risk limits"
    )

    notional_limits: NotionalLimitsConfig = Field(
        default_factory=NotionalLimitsConfig,
        description="Notional position limits"
    )

    compliance: ComplianceConfig = Field(
        default_factory=ComplianceConfig,
        description="Compliance settings"
    )


class StrategyAllocation(BaseModel):
    """Strategy allocation validation."""
    model_config = ConfigDict(extra='allow')

    scalper: float = Field(default=0.4, ge=0.0, le=1.0, description="Scalper allocation")
    trend: float = Field(default=0.3, ge=0.0, le=1.0, description="Trend allocation")
    mean_reversion: float = Field(default=0.2, ge=0.0, le=1.0, description="Mean reversion allocation")
    breakout: float = Field(default=0.1, ge=0.0, le=1.0, description="Breakout allocation")

    @model_validator(mode='after')
    def validate_total_allocation(self) -> 'StrategyAllocation':
        """Validate allocations sum to ~1.0."""
        total = self.scalper + self.trend + self.mean_reversion + self.breakout

        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"Strategy allocations must sum to 1.0, got {total:.4f}"
            )

        return self


class StrategiesConfig(BaseModel):
    """Strategies configuration validation."""
    model_config = ConfigDict(extra='allow')

    allocations: StrategyAllocation = Field(
        default_factory=StrategyAllocation,
        description="Strategy allocations"
    )


class PrometheusConfig(BaseModel):
    """Prometheus monitoring configuration."""
    model_config = ConfigDict(extra='allow')

    enabled: bool = Field(default=True, description="Enable Prometheus metrics")
    port: int = Field(default=9108, ge=1024, le=65535, description="Prometheus port")


class AlertsConfig(BaseModel):
    """Alerts configuration."""
    model_config = ConfigDict(extra='allow')

    level: LogLevel = Field(default=LogLevel.ERROR, description="Alert level")


class MonitoringConfig(BaseModel):
    """Monitoring configuration validation."""
    model_config = ConfigDict(extra='allow')

    prometheus: PrometheusConfig = Field(
        default_factory=PrometheusConfig,
        description="Prometheus configuration"
    )

    alerts: AlertsConfig = Field(
        default_factory=AlertsConfig,
        description="Alerts configuration"
    )


class ModeConfig(BaseModel):
    """Trading mode configuration."""
    model_config = ConfigDict(extra='allow')

    bot_mode: str = Field(default="PAPER", description="Bot mode (PAPER/LIVE)")
    enable_trading: bool = Field(default=False, description="Enable trading")
    live_trading_confirmation: str = Field(default="", description="Live trading confirmation")

    @model_validator(mode='after')
    def validate_live_mode(self) -> 'ModeConfig':
        """Validate live mode safety checks."""
        if self.bot_mode == "LIVE":
            if self.enable_trading and self.live_trading_confirmation != "I_UNDERSTAND_REAL_MONEY":
                raise ValueError(
                    "For live trading, LIVE_TRADING_CONFIRMATION must be set to "
                    "'I_UNDERSTAND_REAL_MONEY' (without quotes)"
                )

        return self


class LoggingConfig(BaseModel):
    """Logging configuration."""
    model_config = ConfigDict(extra='allow')

    level: LogLevel = Field(default=LogLevel.INFO, description="Log level")
    dir: str = Field(default="logs/", description="Log directory")


class DiscordConfig(BaseModel):
    """Discord notification configuration."""
    model_config = ConfigDict(extra='allow')

    enabled: bool = Field(default=False, description="Enable Discord notifications")
    webhook_url: str = Field(
        default="https://discord.com/api/webhooks/disabled",
        description="Discord webhook URL"
    )


class CryptoAIBotConfig(BaseModel):
    """
    PRD-001 Section 7.3: Complete bot configuration validation.

    This model validates the entire config/settings.yaml structure.
    """
    model_config = ConfigDict(extra='allow')

    # Core configuration sections
    mode: ModeConfig = Field(default_factory=ModeConfig, description="Trading mode config")
    logging: LoggingConfig = Field(default_factory=LoggingConfig, description="Logging config")
    redis: RedisConfig = Field(..., description="Redis config (required)")
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig, description="Exchange config")
    risk: RiskConfig = Field(default_factory=RiskConfig, description="Risk config")
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig, description="Strategies config")
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig, description="Monitoring config")
    discord: DiscordConfig = Field(default_factory=DiscordConfig, description="Discord config")


class ConfigValidator:
    """
    PRD-001 Section 7.3 compliant configuration validator.

    Features:
    - Validate configuration with Pydantic models
    - Fail fast on invalid config
    - Type checking, range validation, required fields
    - Comprehensive error messages

    Usage:
        validator = ConfigValidator()

        # Validate config dict
        try:
            validated_config = validator.validate(config_dict)
            print("✓ Configuration valid")
        except ValueError as e:
            print(f"✗ Configuration invalid: {e}")
            sys.exit(1)
    """

    def __init__(self):
        """Initialize config validator."""
        logger.info("ConfigValidator initialized")

    def validate(self, config: Dict[str, Any]) -> CryptoAIBotConfig:
        """
        Validate configuration with Pydantic.

        PRD-001 Section 7.3: Validate config on load (fail fast on invalid config)

        Args:
            config: Configuration dictionary

        Returns:
            Validated CryptoAIBotConfig instance

        Raises:
            ValueError: If configuration is invalid
        """
        try:
            validated_config = CryptoAIBotConfig.model_validate(config)
            logger.info("✓ Configuration validation passed")
            return validated_config

        except Exception as e:
            logger.error(f"✗ Configuration validation failed: {e}")
            raise ValueError(f"Invalid configuration: {e}") from e

    def validate_and_log(self, config: Dict[str, Any]) -> CryptoAIBotConfig:
        """
        Validate configuration and log detailed errors.

        Args:
            config: Configuration dictionary

        Returns:
            Validated CryptoAIBotConfig instance

        Raises:
            ValueError: If configuration is invalid
        """
        try:
            return self.validate(config)
        except ValueError as e:
            # Log detailed error information
            logger.error("=" * 80)
            logger.error("CONFIGURATION VALIDATION FAILED")
            logger.error("=" * 80)
            logger.error(f"Error: {e}")
            logger.error("=" * 80)
            raise


# Singleton instance
_validator_instance: Optional[ConfigValidator] = None


def get_validator() -> ConfigValidator:
    """
    Get singleton ConfigValidator instance.

    Returns:
        ConfigValidator instance
    """
    global _validator_instance

    if _validator_instance is None:
        _validator_instance = ConfigValidator()

    return _validator_instance


# Export for convenience
__all__ = [
    "CryptoAIBotConfig",
    "ConfigValidator",
    "RedisConfig",
    "ExchangeConfig",
    "RiskConfig",
    "StrategiesConfig",
    "MonitoringConfig",
    "TradingMode",
    "LogLevel",
    "get_validator",
]
