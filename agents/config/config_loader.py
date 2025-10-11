"""
Configuration loader for crypto trading agents.

Provides Pydantic v2 models for settings with support for:
- Environment variable loading
- YAML file configuration
- Precedence: CLI > ENV > YAML > defaults
- Validation for trading modes and live trading confirmation
- Redis TLS connection support
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# ======================== Pydantic v2 Models ========================


class RedisSettings(BaseModel):
    """Redis connection settings with TLS support."""

    url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL (use rediss:// for TLS)",
    )
    ca_cert_path: str | None = Field(
        default=None,
        description="Path to CA certificate for TLS verification",
    )
    client_cert_path: str | None = Field(
        default=None,
        description="Path to client certificate for mTLS",
    )
    client_key_path: str | None = Field(
        default=None,
        description="Path to client key for mTLS",
    )
    socket_timeout: float = Field(
        default=5.0,
        description="Socket operation timeout in seconds",
    )
    socket_connect_timeout: float = Field(
        default=5.0,
        description="Socket connection timeout in seconds",
    )
    decode_responses: bool = Field(
        default=False,
        description="Whether to decode responses to strings",
    )
    max_connections: int = Field(
        default=50,
        description="Maximum number of connections in pool",
    )

    def to_redis_kwargs(self) -> dict[str, Any]:
        """
        Convert settings to redis-py connection kwargs.

        Returns:
            Dictionary of connection parameters for redis.from_url()

        Raises:
            FileNotFoundError: If certificate files don't exist
        """
        import os
        import ssl

        kwargs: dict[str, Any] = {
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.socket_connect_timeout,
            "decode_responses": self.decode_responses,
            "max_connections": self.max_connections,
        }

        # Add TLS/SSL context if using rediss://
        if self.url.startswith("rediss://"):
            if self.ca_cert_path:
                # Verify CA cert exists
                if not os.path.exists(self.ca_cert_path):
                    raise FileNotFoundError(
                        f"CA certificate not found: {self.ca_cert_path}"
                    )

                ctx = ssl.create_default_context(cafile=self.ca_cert_path)
                ctx.check_hostname = True
                ctx.verify_mode = ssl.CERT_REQUIRED

                # Add mTLS if both cert and key provided
                if self.client_cert_path and self.client_key_path:
                    if not os.path.exists(self.client_cert_path):
                        raise FileNotFoundError(
                            f"Client certificate not found: {self.client_cert_path}"
                        )
                    if not os.path.exists(self.client_key_path):
                        raise FileNotFoundError(
                            f"Client key not found: {self.client_key_path}"
                        )
                    ctx.load_cert_chain(self.client_cert_path, self.client_key_path)

                kwargs["ssl_context"] = ctx

        return kwargs


class KrakenSettings(BaseModel):
    """Kraken API settings."""

    api_key: str = Field(
        default="",
        description="Kraken API key",
    )
    api_secret: str = Field(
        default="",
        description="Kraken API secret (base64 encoded)",
    )
    api_url: str = Field(
        default="https://api.kraken.com",
        description="Kraken API base URL",
    )
    api_version: str = Field(
        default="0",
        description="Kraken API version",
    )
    rate_limit_calls_per_second: float = Field(
        default=1.0,
        description="API call rate limit (calls per second)",
    )
    rate_limit_burst_size: float = Field(
        default=2.0,
        description="Rate limiter burst size",
    )

    @field_validator("api_key", "api_secret")
    @classmethod
    def validate_credentials(cls, v: str, info: Any) -> str:
        """Validate API credentials are provided in live mode."""
        # Note: actual validation happens at Settings level
        return v


class RiskSettings(BaseModel):
    """Risk management settings."""

    max_position_size_usd: float = Field(
        default=10000.0,
        description="Maximum position size in USD",
    )
    max_daily_loss_usd: float = Field(
        default=500.0,
        description="Maximum daily loss in USD",
    )
    max_drawdown_percent: float = Field(
        default=10.0,
        description="Maximum drawdown percentage",
    )
    max_leverage: float = Field(
        default=1.0,
        description="Maximum leverage allowed",
    )
    position_timeout_seconds: int = Field(
        default=300,
        description="Maximum time to hold a position (seconds)",
    )

    @field_validator("max_leverage")
    @classmethod
    def validate_leverage(cls, v: float) -> float:
        """Validate leverage is positive and reasonable."""
        if v <= 0:
            raise ValueError("max_leverage must be positive")
        if v > 10:
            raise ValueError("max_leverage must be <= 10 for safety")
        return v


class ScalperSettings(BaseModel):
    """Scalping strategy settings."""

    enabled: bool = Field(
        default=True,
        description="Whether scalping is enabled",
    )
    max_toxicity_score: float = Field(
        default=0.6,
        description="Maximum toxicity score for scalp entry",
    )
    max_adverse_selection_risk: float = Field(
        default=0.7,
        description="Maximum adverse selection risk",
    )
    max_market_impact_risk: float = Field(
        default=0.8,
        description="Maximum market impact risk",
    )
    cooldown_after_loss_seconds: int = Field(
        default=90,
        description="Cooldown period after loss (seconds)",
    )
    min_spread_bps: float = Field(
        default=2.0,
        description="Minimum spread in basis points",
    )
    target_profit_bps: float = Field(
        default=5.0,
        description="Target profit in basis points",
    )

    @field_validator("max_toxicity_score", "max_adverse_selection_risk", "max_market_impact_risk")
    @classmethod
    def validate_risk_scores(cls, v: float) -> float:
        """Validate risk scores are in valid range."""
        if not 0 <= v <= 1:
            raise ValueError("Risk scores must be between 0 and 1")
        return v


class Settings(BaseModel):
    """Main settings container with all configuration."""

    # Core settings
    mode: Literal["paper", "live"] = Field(
        default="paper",
        description="Trading mode: paper or live",
    )
    live_trading_confirmation: str = Field(
        default="",
        description="Live trading confirmation string",
    )
    environment: str = Field(
        default="prod",
        description="Environment: dev, staging, prod",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )

    # Component settings
    redis: RedisSettings = Field(
        default_factory=RedisSettings,
        description="Redis connection settings",
    )
    kraken: KrakenSettings = Field(
        default_factory=KrakenSettings,
        description="Kraken API settings",
    )
    risk: RiskSettings = Field(
        default_factory=RiskSettings,
        description="Risk management settings",
    )
    scalper: ScalperSettings = Field(
        default_factory=ScalperSettings,
        description="Scalping strategy settings",
    )

    @model_validator(mode="after")
    def validate_live_trading(self) -> Settings:
        """Validate live trading requires confirmation."""
        if self.mode == "live":
            if self.live_trading_confirmation != "I-accept-the-risk":
                raise ValueError(
                    "Live trading requires LIVE_TRADING_CONFIRMATION='I-accept-the-risk'"
                )
            # Validate Kraken credentials are provided
            if not self.kraken.api_key or not self.kraken.api_secret:
                raise ValueError(
                    "Live trading requires Kraken API credentials "
                    "(KRAKEN_API_KEY and KRAKEN_API_SECRET)"
                )
        return self

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        """Validate mode is paper or live."""
        if v not in ("paper", "live"):
            raise ValueError("mode must be 'paper' or 'live'")
        return v


# ======================== Configuration Loader ========================


def load_agent_settings(
    env: Mapping[str, str] | None = None,
    file: Path | None = None,
) -> Settings:
    """
    Load agent settings with precedence: CLI > ENV > YAML > defaults.

    Args:
        env: Environment variables mapping (uses os.environ if None)
        file: Path to YAML configuration file (optional)

    Returns:
        Validated Settings object

    Raises:
        ValueError: If configuration is invalid
        FileNotFoundError: If YAML file specified but not found

    Example:
        >>> # Load from environment only
        >>> settings = load_agent_settings()
        >>>
        >>> # Load from YAML with env overrides
        >>> settings = load_agent_settings(file=Path("config.yaml"))
        >>>
        >>> # Load with custom env (useful for testing)
        >>> settings = load_agent_settings(env={"MODE": "paper"})
    """
    if env is None:
        env = os.environ

    # Start with defaults (Pydantic defaults)
    config_data: dict[str, Any] = {}

    # Layer 1: Load from YAML if provided
    if file is not None:
        if not file.exists():
            raise FileNotFoundError(f"Configuration file not found: {file}")

        with open(file, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}

        # Merge YAML data
        config_data.update(yaml_data)

    # Layer 2: Override with environment variables
    # Core settings
    if "MODE" in env:
        config_data["mode"] = env["MODE"]
    if "LIVE_TRADING_CONFIRMATION" in env:
        config_data["live_trading_confirmation"] = env["LIVE_TRADING_CONFIRMATION"]
    if "ENVIRONMENT" in env:
        config_data["environment"] = env["ENVIRONMENT"]
    if "LOG_LEVEL" in env:
        config_data["log_level"] = env["LOG_LEVEL"]

    # Redis settings
    redis_data = config_data.get("redis", {})
    if "REDIS_URL" in env:
        redis_data["url"] = env["REDIS_URL"]
    if "REDIS_CA_CERT_PATH" in env:
        redis_data["ca_cert_path"] = env["REDIS_CA_CERT_PATH"]
    if "REDIS_CLIENT_CERT_PATH" in env:
        redis_data["client_cert_path"] = env["REDIS_CLIENT_CERT_PATH"]
    if "REDIS_CLIENT_KEY_PATH" in env:
        redis_data["client_key_path"] = env["REDIS_CLIENT_KEY_PATH"]
    if "REDIS_SOCKET_TIMEOUT" in env:
        redis_data["socket_timeout"] = float(env["REDIS_SOCKET_TIMEOUT"])
    if "REDIS_SOCKET_CONNECT_TIMEOUT" in env:
        redis_data["socket_connect_timeout"] = float(env["REDIS_SOCKET_CONNECT_TIMEOUT"])
    if "REDIS_MAX_CONNECTIONS" in env:
        redis_data["max_connections"] = int(env["REDIS_MAX_CONNECTIONS"])
    if redis_data:
        config_data["redis"] = redis_data

    # Kraken settings
    kraken_data = config_data.get("kraken", {})
    if "KRAKEN_API_KEY" in env:
        kraken_data["api_key"] = env["KRAKEN_API_KEY"]
    if "KRAKEN_API_SECRET" in env:
        kraken_data["api_secret"] = env["KRAKEN_API_SECRET"]
    if "KRAKEN_API_URL" in env:
        kraken_data["api_url"] = env["KRAKEN_API_URL"]
    if "KRAKEN_API_VERSION" in env:
        kraken_data["api_version"] = env["KRAKEN_API_VERSION"]
    if "KRAKEN_RATE_LIMIT_CALLS_PER_SECOND" in env:
        kraken_data["rate_limit_calls_per_second"] = float(
            env["KRAKEN_RATE_LIMIT_CALLS_PER_SECOND"]
        )
    if "KRAKEN_RATE_LIMIT_BURST_SIZE" in env:
        kraken_data["rate_limit_burst_size"] = float(env["KRAKEN_RATE_LIMIT_BURST_SIZE"])
    if kraken_data:
        config_data["kraken"] = kraken_data

    # Risk settings
    risk_data = config_data.get("risk", {})
    if "RISK_MAX_POSITION_SIZE_USD" in env:
        risk_data["max_position_size_usd"] = float(env["RISK_MAX_POSITION_SIZE_USD"])
    if "RISK_MAX_DAILY_LOSS_USD" in env:
        risk_data["max_daily_loss_usd"] = float(env["RISK_MAX_DAILY_LOSS_USD"])
    if "RISK_MAX_DRAWDOWN_PERCENT" in env:
        risk_data["max_drawdown_percent"] = float(env["RISK_MAX_DRAWDOWN_PERCENT"])
    if "RISK_MAX_LEVERAGE" in env:
        risk_data["max_leverage"] = float(env["RISK_MAX_LEVERAGE"])
    if "RISK_POSITION_TIMEOUT_SECONDS" in env:
        risk_data["position_timeout_seconds"] = int(env["RISK_POSITION_TIMEOUT_SECONDS"])
    if risk_data:
        config_data["risk"] = risk_data

    # Scalper settings
    scalper_data = config_data.get("scalper", {})
    if "SCALPER_ENABLED" in env:
        scalper_data["enabled"] = env["SCALPER_ENABLED"].lower() in ("true", "1", "yes")
    if "SCALP_MAX_TOXICITY_SCORE" in env:
        scalper_data["max_toxicity_score"] = float(env["SCALP_MAX_TOXICITY_SCORE"])
    if "SCALP_MAX_ADVERSE_SELECTION_RISK" in env:
        scalper_data["max_adverse_selection_risk"] = float(
            env["SCALP_MAX_ADVERSE_SELECTION_RISK"]
        )
    if "SCALP_MAX_MARKET_IMPACT_RISK" in env:
        scalper_data["max_market_impact_risk"] = float(env["SCALP_MAX_MARKET_IMPACT_RISK"])
    if "SCALP_COOLDOWN_AFTER_LOSS_SECONDS" in env:
        scalper_data["cooldown_after_loss_seconds"] = int(
            env["SCALP_COOLDOWN_AFTER_LOSS_SECONDS"]
        )
    if "SCALP_MIN_SPREAD_BPS" in env:
        scalper_data["min_spread_bps"] = float(env["SCALP_MIN_SPREAD_BPS"])
    if "SCALP_TARGET_PROFIT_BPS" in env:
        scalper_data["target_profit_bps"] = float(env["SCALP_TARGET_PROFIT_BPS"])
    if scalper_data:
        config_data["scalper"] = scalper_data

    # Create and validate Settings object
    return Settings(**config_data)


# ======================== Legacy Compatibility ========================


class SimpleConfig:
    """Legacy compatibility class for old code."""

    def __init__(self, settings: Settings | None = None):
        if settings is None:
            settings = load_agent_settings()
        self.settings = settings
        self._build_data_dict()

    def _build_data_dict(self) -> None:
        """Build legacy data dict from Settings."""
        self.data = {
            # Toxic flow settings (scalper)
            "TOXIC_IMBALANCE_THRESHOLD": 0.8,
            "TOXIC_VOLATILITY_THRESHOLD": 50.0,
            "TOXIC_MOMENTUM_THRESHOLD": 0.7,
            "TOXIC_CASCADE_VOLUME_MULT": 3.0,
            # Scalping settings
            "SCALP_MAX_TOXICITY_SCORE": self.settings.scalper.max_toxicity_score,
            "SCALP_MAX_ADVERSE_SELECTION_RISK": self.settings.scalper.max_adverse_selection_risk,
            "SCALP_MAX_MARKET_IMPACT_RISK": self.settings.scalper.max_market_impact_risk,
            "SCALP_COOLDOWN_AFTER_LOSS_SECONDS": self.settings.scalper.cooldown_after_loss_seconds,
            # General settings
            "ENVIRONMENT": self.settings.environment,
            "LOG_LEVEL": self.settings.log_level,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access."""
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        """Allow 'in' operator."""
        return key in self.data


# Global config instance
_config_instance: SimpleConfig | None = None


def get_config() -> SimpleConfig:
    """Get the global configuration instance (legacy)."""
    global _config_instance
    if _config_instance is None:
        _config_instance = SimpleConfig()
    return _config_instance


def reload_config() -> SimpleConfig:
    """Force reload the configuration (legacy)."""
    global _config_instance
    _config_instance = SimpleConfig()
    return _config_instance


class ConfigLoader:
    """Config loader class for compatibility (legacy)."""

    def load_config(self) -> SimpleConfig:
        return get_config()
