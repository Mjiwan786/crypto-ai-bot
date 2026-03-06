"""
Market Data Configuration

Pydantic v2 models for market data layer configuration.
Loads from YAML with environment variable substitution.

Example:
    from market_data.config import load_market_data_config

    config = load_market_data_config("config/market_data.yaml")
    print(config.enabled_exchanges)  # ["kraken", "binance"]
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ==============================================================================
# Configuration Models
# ==============================================================================


class FeatureFlagsConfig(BaseModel):
    """Feature flags for enabling/disabling components."""

    market_data_enabled: bool = True
    multi_exchange_feeds: bool = True
    price_engine_enabled: bool = True
    health_monitoring: bool = True
    outlier_filtering: bool = True


class PollingConfig(BaseModel):
    """Polling configuration for data feeds."""

    interval_sec: float = Field(default=2.0, ge=0.5, le=60.0)
    max_concurrent_requests: int = Field(default=10, ge=1, le=50)
    request_timeout_sec: float = Field(default=10.0, ge=1.0, le=60.0)


class OutlierFilterConfig(BaseModel):
    """Outlier filtering configuration."""

    enabled: bool = True
    max_deviation_pct: float = Field(default=1.5, ge=0.1, le=10.0)
    min_exchanges_for_filter: int = Field(default=2, ge=2, le=10)


class HealthConfig(BaseModel):
    """Health monitoring configuration."""

    stale_after_sec: float = Field(default=10.0, ge=1.0, le=300.0)
    error_window_sec: float = Field(default=300.0, ge=60.0, le=3600.0)
    max_errors_before_unhealthy: int = Field(default=5, ge=1, le=100)
    heartbeat_interval_sec: float = Field(default=5.0, ge=1.0, le=60.0)


class RedisStreamsConfig(BaseModel):
    """Redis stream naming templates."""

    raw_ticker: str = "market:raw:{exchange}:{pair}"
    price: str = "market:price:{pair}"
    spread: str = "market:spread:{pair}"
    exchange_health: str = "exchange:health:{exchange}"


class RedisMaxlenConfig(BaseModel):
    """Redis stream max lengths."""

    raw_ticker: int = Field(default=10000, ge=100, le=1000000)
    price: int = Field(default=10000, ge=100, le=1000000)
    spread: int = Field(default=5000, ge=100, le=1000000)
    exchange_health: int = Field(default=1000, ge=100, le=100000)


class RedisConfig(BaseModel):
    """Redis configuration."""

    streams: RedisStreamsConfig = Field(default_factory=RedisStreamsConfig)
    maxlen: RedisMaxlenConfig = Field(default_factory=RedisMaxlenConfig)


class ExchangeOverrideConfig(BaseModel):
    """Per-exchange configuration overrides."""

    symbol_map: Dict[str, str] = Field(default_factory=dict)
    rate_limit_ms: int = Field(default=1000, ge=50, le=10000)


class ConfidenceConfig(BaseModel):
    """Confidence calculation parameters."""

    base_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    penalty_per_missing_exchange: float = Field(default=0.2, ge=0.0, le=0.5)
    penalty_no_spread: float = Field(default=0.2, ge=0.0, le=0.5)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    max_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    log_every_n_ticks: int = Field(default=100, ge=1, le=10000)
    log_price_updates: bool = False


class MarketDataConfig(BaseModel):
    """Complete market data configuration."""

    feature_flags: FeatureFlagsConfig = Field(default_factory=FeatureFlagsConfig)
    enabled_exchanges: List[str] = Field(default_factory=lambda: ["kraken", "binance"])
    pairs: List[str] = Field(default_factory=lambda: ["BTC/USD", "ETH/USD", "SOL/USD"])
    polling: PollingConfig = Field(default_factory=PollingConfig)
    weights: Dict[str, float] = Field(default_factory=lambda: {"kraken": 0.4, "binance": 0.6})
    outlier_filter: OutlierFilterConfig = Field(default_factory=OutlierFilterConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    exchange_overrides: Dict[str, ExchangeOverrideConfig] = Field(default_factory=dict)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, v: Dict[str, float]) -> Dict[str, float]:
        """Validate that weights are positive."""
        for exchange, weight in v.items():
            if weight < 0:
                raise ValueError(f"Weight for {exchange} must be non-negative")
        return v

    @field_validator("enabled_exchanges")
    @classmethod
    def validate_exchanges(cls, v: List[str]) -> List[str]:
        """Validate exchange list."""
        if not v:
            raise ValueError("At least one exchange must be enabled")
        return [e.lower() for e in v]

    @field_validator("pairs")
    @classmethod
    def validate_pairs(cls, v: List[str]) -> List[str]:
        """Validate pair format."""
        for pair in v:
            if "/" not in pair:
                raise ValueError(f"Invalid pair format: {pair}. Expected BASE/QUOTE")
        return v

    def get_weight(self, exchange: str) -> float:
        """Get weight for an exchange, defaulting to equal weight."""
        if exchange in self.weights:
            return self.weights[exchange]
        # Default to equal weight
        return 1.0 / len(self.enabled_exchanges)

    def get_symbol_for_exchange(self, exchange: str, pair: str) -> str:
        """Get the exchange-specific symbol for a pair.

        Args:
            exchange: Exchange name (e.g., "kraken")
            pair: Internal pair format (e.g., "BTC/USD")

        Returns:
            Exchange-specific symbol (e.g., "XBT/USD" for Kraken)
        """
        override = self.exchange_overrides.get(exchange)
        if override and pair in override.symbol_map:
            return override.symbol_map[pair]
        return pair


# ==============================================================================
# Config Loading
# ==============================================================================


def _substitute_env_vars(value: Any) -> Any:
    """Recursively substitute ${VAR} or ${VAR:default} patterns with env values."""
    if isinstance(value, str):
        # Pattern: ${VAR} or ${VAR:default}
        pattern = r"\$\{([^}:]+)(?::([^}]*))?\}"

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2)
            env_value = os.getenv(var_name)
            if env_value is not None:
                return env_value
            if default is not None:
                return default
            return match.group(0)  # Return original if no value/default

        return re.sub(pattern, replacer, value)
    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    return value


def load_market_data_config(
    config_path: Optional[str] = None,
    env_prefix: str = "MARKET_DATA_",
) -> MarketDataConfig:
    """Load market data configuration from YAML file.

    Args:
        config_path: Path to YAML config file. If None, uses default path.
        env_prefix: Prefix for environment variable overrides.

    Returns:
        MarketDataConfig instance.

    Raises:
        FileNotFoundError: If config file not found.
        ValueError: If config validation fails.
    """
    # Default config path
    if config_path is None:
        config_path = os.getenv(
            f"{env_prefix}CONFIG_PATH",
            "config/market_data.yaml",
        )

    path = Path(config_path)
    if not path.exists():
        # Try relative to current directory
        alt_path = Path("config/market_data.yaml")
        if alt_path.exists():
            path = alt_path
        else:
            raise FileNotFoundError(f"Market data config not found: {config_path}")

    logger.info(f"Loading market data config from: {path}")

    # Load YAML
    with open(path, "r") as f:
        raw_config = yaml.safe_load(f)

    # Substitute environment variables
    config_data = _substitute_env_vars(raw_config)

    # Parse with Pydantic
    config = MarketDataConfig.model_validate(config_data)

    logger.info(
        f"Market data config loaded: {len(config.enabled_exchanges)} exchanges, "
        f"{len(config.pairs)} pairs"
    )

    return config


# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    "MarketDataConfig",
    "FeatureFlagsConfig",
    "PollingConfig",
    "OutlierFilterConfig",
    "HealthConfig",
    "RedisConfig",
    "ExchangeOverrideConfig",
    "ConfidenceConfig",
    "LoggingConfig",
    "load_market_data_config",
]
