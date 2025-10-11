"""
Base configuration classes and validation for crypto-ai-bot.

This module contains the core Pydantic models and validation logic
that the enhanced config_loader.py depends on.
"""

from __future__ import annotations

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union, Any, Literal
from datetime import datetime

# Pydantic v2 compatibility
try:
    from pydantic import BaseModel, Field, field_validator, ConfigDict
    from pydantic import ValidationError
except ImportError:
    raise ImportError("pydantic is required for configuration validation")


# =============================================================================
# Core Configuration Models
# =============================================================================

class MetaConfig(BaseModel):
    """Application metadata configuration."""
    model_config = ConfigDict(extra="forbid")
    
    app_name: str = "crypto-ai-bot"
    environment: Literal["prod", "staging", "dev", "test"] = "prod"
    timezone: str = "UTC"
    seeds: Dict[str, int] = Field(default_factory=lambda: {"global": 1337, "ml": 2025})


class LoggingConfig(BaseModel):
    """Logging configuration."""
    model_config = ConfigDict(extra="forbid")
    
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    json_format: bool = Field(alias="json", default=True)
    dir: str = "logs"
    file: str = "logs/crypto_ai_bot.log"
    verbose: bool = False


class ModeConfig(BaseModel):
    """Bot mode and trading configuration."""
    model_config = ConfigDict(extra="forbid")
    
    bot_mode: Literal["PAPER", "LIVE", "BACKTEST", "STOP"] = "PAPER"
    enable_trading: bool = False
    live_trading_confirmation: str = ""


class ServerConfig(BaseModel):
    """Server configuration."""
    model_config = ConfigDict(extra="forbid")
    
    host: str = "0.0.0.0"
    port: int = 9000
    enable_metrics: bool = True
    enable_health: bool = True
    concurrency: int = 2
    heartbeat_interval: int = 30
    read_timeout_ms: int = 5000


class RedisSSLConfig(BaseModel):
    """Redis SSL configuration."""
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = True
    cert_reqs: Literal["required", "none"] = "required"
    check_hostname: bool = True
    ca_cert_use_certifi: bool = True
    ca_cert_path: str = "config/certs/redis_ca.pem"


class RedisPoolConfig(BaseModel):
    """Redis connection pool configuration."""
    model_config = ConfigDict(extra="forbid")
    
    max_connections: int = 30


class RedisTimeoutsConfig(BaseModel):
    """Redis timeout configuration."""
    model_config = ConfigDict(extra="forbid")
    
    socket_timeout: int = 10
    socket_connect_timeout: int = 10
    health_check_interval: int = 15


class RedisStreamsConfig(BaseModel):
    """Redis streams configuration."""
    model_config = ConfigDict(extra="forbid")
    
    md_trades: str = "md:trades"
    md_spread: str = "md:spread"
    md_book: str = "md:orderbook"
    md_candles: str = "md:candles"
    signals_paper: str = "signals:paper"
    signals_live: str = "signals:live"
    active_signals: str = "signals:paper"
    events: str = "events:bus"
    orders_req: str = "orders:requests"
    orders_conf: str = "orders:confirmations"


class RedisStreamOptsConfig(BaseModel):
    """Redis stream options configuration."""
    model_config = ConfigDict(extra="forbid")
    
    max_len: int = 10000
    trim_strategy: Literal["approx", "exact"] = "approx"
    batch_size: int = 50
    pipeline_threshold: int = 25
    compression: Dict[str, Any] = Field(default_factory=lambda: {
        "enabled": True,
        "threshold_kb": 2
    })


class RedisConfig(BaseModel):
    """Redis configuration."""
    model_config = ConfigDict(extra="forbid")
    
    url: str = Field(description="Redis URL from environment")
    db: int = 0
    client_name: str = "crypto-ai-bot"
    decode_responses: bool = True
    pool: RedisPoolConfig = Field(default_factory=RedisPoolConfig)
    timeouts: RedisTimeoutsConfig = Field(default_factory=RedisTimeoutsConfig)
    retry_on_timeout: bool = True
    ssl: RedisSSLConfig = Field(default_factory=RedisSSLConfig)
    streams: RedisStreamsConfig = Field(default_factory=RedisStreamsConfig)
    stream_opts: RedisStreamOptsConfig = Field(default_factory=RedisStreamOptsConfig)


class HealthConfig(BaseModel):
    """Health monitoring configuration."""
    model_config = ConfigDict(extra="forbid")
    
    freshness_ms: Dict[str, int] = Field(default_factory=lambda: {
        "md_trades": 2000,
        "md_spread": 2000,
        "md_book": 2000,
        "md_candles": 2000
    })
    redis: Dict[str, Any] = Field(default_factory=lambda: {
        "startup_validate": True,
        "startup_timeout_seconds": 30,
        "check_on_startup": True,
        "write_read_self_test": True
    })
    kraken_ws: Dict[str, str] = Field(default_factory=lambda: {
        "url": "wss://ws.kraken.com",
        "ping_topic": "heartbeat"
    })


class KrakenConfig(BaseModel):
    """Kraken exchange configuration."""
    model_config = ConfigDict(extra="forbid")
    
    api_url: str = "https://api.kraken.com"
    sandbox: bool = False
    market_type: Literal["spot", "futures"] = "spot"
    pairs: List[str] = Field(default_factory=lambda: ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD"])
    fees_bps: Dict[str, int] = Field(default_factory=lambda: {"maker": 16, "taker": 26})
    rate_limit_guard: bool = True
    ws: Dict[str, Any] = Field(default_factory=lambda: {
        "enabled": True,
        "reconnect_delay_sec": 5,
        "max_retries": 10,
        "ping_interval_sec": 20,
        "close_timeout_sec": 5
    })


class OrderPrefsConfig(BaseModel):
    """Order preferences configuration."""
    model_config = ConfigDict(extra="forbid")
    
    default_type: str = "limit"
    time_in_force: str = "GTC"
    post_only: bool = True
    hidden_orders: bool = True
    partial_fill: bool = True
    order_retry: int = 2
    price_precision_mode: Literal["exchange", "strict"] = "exchange"
    slippage_bps_max: int = 10


class ExchangeConfig(BaseModel):
    """Exchange configuration."""
    model_config = ConfigDict(extra="forbid")
    
    primary: str = "kraken"
    kraken: KrakenConfig = Field(default_factory=KrakenConfig)
    order_prefs: OrderPrefsConfig = Field(default_factory=OrderPrefsConfig)


class RiskConfig(BaseModel):
    """Risk management configuration."""
    model_config = ConfigDict(extra="forbid")
    
    portfolio: Dict[str, float] = Field(default_factory=lambda: {
        "max_drawdown_pct": 25.0,
        "max_single_position_notional_usd": 2000
    })
    notional_limits: Dict[str, float] = Field(default_factory=lambda: {
        "min_usd": 10.0,
        "max_usd": 10000.0
    })
    compliance: Dict[str, Any] = Field(default_factory=lambda: {
        "kill_switch": False,
        "allowed_symbols": ["BTC/USD", "ETH/USD", "SOL/USD"],
        "banned_symbols": [],
        "quote_currencies_allowed": ["USD"],
        "allowed_hours_utc": ["00:00-24:00"],
        "per_symbol_size": {}
    })
    volatility_shield: Dict[str, Any] = Field(default_factory=lambda: {
        "enabled": True,
        "max_atr_threshold": 0.05
    })
    dead_mans_switch: Dict[str, Any] = Field(default_factory=lambda: {
        "enabled": True,
        "timeout_hours": 6
    })


class StrategyConfig(BaseModel):
    """Strategy configuration."""
    model_config = ConfigDict(extra="forbid")
    
    active: List[str] = Field(default_factory=lambda: ["trend_following", "scalping"])
    allocations: Dict[str, float] = Field(default_factory=lambda: {
        "trend_following": 0.60,
        "scalping": 0.40
    })
    trend_following: Dict[str, Any] = Field(default_factory=dict)
    scalping: Dict[str, Any] = Field(default_factory=dict)


class ExecutionConfig(BaseModel):
    """Execution configuration."""
    model_config = ConfigDict(extra="forbid")
    
    taker_fee_bps: int = 26
    maker_fee_bps: int = 16
    default_order_type: str = "limit"
    time_in_force: str = "GTC"
    post_only: bool = True
    slippage_bps_max: int = 10


class MarketDataConfig(BaseModel):
    """Market data configuration."""
    model_config = ConfigDict(extra="forbid")
    
    replay: bool = False
    book_depth: int = 25
    trades_buffer: int = 2000


class MCPConfig(BaseModel):
    """MCP (Model Context Protocol) configuration."""
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = True
    role: str = "brain"
    planning_mode: str = "plan_act_reflect"
    schemas_path: str = "mcp/schemas"
    memory_backend: str = "redis"
    context_window: int = 8
    parallel_workers: int = 4
    timeouts_ms: Dict[str, int] = Field(default_factory=lambda: {
        "plan": 800,
        "act": 400,
        "reflect": 600,
        "health_check": 5000
    })
    reflection: Dict[str, Any] = Field(default_factory=lambda: {
        "enabled": True,
        "depth": 2
    })
    circuit_breakers: Dict[str, Any] = Field(default_factory=lambda: {
        "timeouts": 3,
        "window_seconds": 30
    })


class AIConfig(BaseModel):
    """AI configuration."""
    model_config = ConfigDict(extra="forbid")
    
    openai: Dict[str, Any] = Field(default_factory=lambda: {
        "enabled": True,
        "model": "gpt-4o-mini",
        "temperature": 0.3,
        "max_tokens": 4000,
        "timeout_seconds": 30
    })
    anthropic: Dict[str, Any] = Field(default_factory=lambda: {
        "enabled": False,
        "model": "claude-3-5-sonnet-latest"
    })
    strategy_selector: Dict[str, bool] = Field(default_factory=lambda: {"enabled": True})


class MLConfig(BaseModel):
    """Machine learning configuration."""
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = False
    models_dir: str = "models"
    symbols: List[str] = Field(default_factory=lambda: ["BTC_USD"])
    warmup_enabled: bool = True
    trend_model_path: str = "models/prod_trend_model_v15.h5"
    scalping_model_path: str = "models/prod_scalp_model_v8.h5"
    thresholds: Dict[str, float] = Field(default_factory=lambda: {
        "trend_confidence": 0.65,
        "scalping_confidence": 0.75
    })
    prediction_window: int = 6


class SentimentConfig(BaseModel):
    """Sentiment analysis configuration."""
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = True
    symbols: List[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    window_minutes: int = 60
    score_threshold: float = 0.15
    reddit: Dict[str, Any] = Field(default_factory=lambda: {
        "subreddits": ["CryptoCurrency", "Bitcoin", "Ethereum", "ethtrader", "CryptoMarkets"]
    })
    twitter: Dict[str, bool] = Field(default_factory=lambda: {"enabled": True})


class MonitoringConfig(BaseModel):
    """Monitoring configuration."""
    model_config = ConfigDict(extra="forbid")
    
    prometheus: Dict[str, Any] = Field(default_factory=lambda: {
        "enabled": True,
        "port": 9108
    })
    alerts: Dict[str, str] = Field(default_factory=lambda: {"level": "ERROR"})
    thresholds: Dict[str, Union[int, float]] = Field(default_factory=lambda: {
        "redis_latency_ms_warn": 100,
        "redis_memory_mb_warn": 200,
        "redis_connections_warn": 12,
        "redis_error_rate_warn": 0.05
    })


class DiscordConfig(BaseModel):
    """Discord configuration."""
    model_config = ConfigDict(extra="forbid")
    
    enabled: bool = True
    webhook_url: str = Field(description="Discord webhook URL from environment")
    bot: Dict[str, str] = Field(default_factory=lambda: {
        "token": "${DISCORD_BOT_TOKEN}",
        "prefix": "!",
        "alert_channel_id": "${DISCORD_BOT_ALERT_CHANNEL_ID}",
        "admin_role": "Admin"
    })


class BacktestConfig(BaseModel):
    """Backtest configuration."""
    model_config = ConfigDict(extra="forbid")
    
    start: str = "2025-01-01T00:00:00Z"
    end: str = "2025-09-20T00:00:00Z"
    base_currency: str = "USD"
    starting_equity: float = 10000.0
    commission_bps: int = 16
    slippage_bps: int = 5
    warmup_bars: int = 300


class DevOverridesConfig(BaseModel):
    """Development overrides configuration."""
    model_config = ConfigDict(extra="forbid")
    
    dry_run: bool = False
    sandbox: bool = False
    strict_config: bool = True
    validate_allocations: bool = True
    fail_fast_on_policy_error: bool = True
    test_disable_sentiment: bool = False
    test_disable_mcp: bool = False


class CryptoAIBotConfig(BaseModel):
    """Main configuration class for crypto-ai-bot."""
    model_config = ConfigDict(extra="allow")
    
    meta: MetaConfig = Field(default_factory=MetaConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    mode: ModeConfig = Field(default_factory=ModeConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    strategies: StrategyConfig = Field(default_factory=StrategyConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    ml: MLConfig = Field(default_factory=MLConfig)
    sentiment: SentimentConfig = Field(default_factory=SentimentConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    dev_overrides: DevOverridesConfig = Field(default_factory=DevOverridesConfig)

    @field_validator('strategies')
    @classmethod
    def validate_allocations(cls, v):
        """Validate that strategy allocations sum to approximately 1.0."""
        if hasattr(v, 'allocations'):
            total = sum(v.allocations.values())
            if abs(total - 1.0) > 0.01:
                raise ValueError(f"Strategy allocations must sum to 1.0, got {total}")
        return v


# =============================================================================
# Configuration Loader
# =============================================================================

class ConfigLoader:
    """Configuration loader that merges YAML files and environment variables."""
    
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.config_dir = self.config_path.parent
        
        # List of YAML files to load in order of increasing precedence
        self.files = [
            "settings.yaml",
            "agent_settings.yaml", 
            "scalping_settings.yaml",
        ]
    
    def _load_yaml(self, name: str) -> Dict[str, Any]:
        """Load a YAML file and return its contents as a dictionary."""
        path = self.config_dir / name
        if not path.exists():
            return {}
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    
    def _substitute_env_vars(self, data: Any) -> Any:
        """Recursively substitute environment variables in configuration data."""
        if isinstance(data, dict):
            return {k: self._substitute_env_vars(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._substitute_env_vars(item) for item in data]
        elif isinstance(data, str) and data.startswith("${") and data.endswith("}"):
            # Extract variable name and default value
            var_expr = data[2:-1]  # Remove ${ and }
            if ":-" in var_expr:
                var_name, default_value = var_expr.split(":-", 1)
                return os.environ.get(var_name, default_value)
            else:
                return os.environ.get(var_expr, data)
        else:
            return data
    
    def load_raw_config(self) -> Dict[str, Any]:
        """Load and merge configuration from YAML files and environment variables."""
        config: Dict[str, Any] = {}
        
        # Merge YAML files
        for fname in self.files:
            config.update(self._load_yaml(fname))
        
        # Substitute environment variables
        config = self._substitute_env_vars(config)
        
        # Override with direct environment variables
        for key, value in os.environ.items():
            if key.startswith(("REDIS_", "DISCORD_", "SCALP_", "ML_")):
                config[key] = value
        
        return config
    
    def load_config(self) -> CryptoAIBotConfig:
        """Load and validate configuration."""
        raw_config = self.load_raw_config()
        return CryptoAIBotConfig(**raw_config)


# =============================================================================
# Configuration Validator
# =============================================================================

class ConfigValidator:
    """Configuration validator with deployment readiness checks."""
    
    def __init__(self):
        self.logger = logging.getLogger("config.validator")
    
    def validate_strategy_consistency(self, config: CryptoAIBotConfig) -> List[str]:
        """Validate strategy configuration consistency."""
        issues = []
        
        # Check allocations sum to 1.0
        total_allocation = sum(config.strategies.allocations.values())
        if abs(total_allocation - 1.0) > 0.01:
            issues.append(f"Strategy allocations sum to {total_allocation}, should be 1.0")
        
        # Check active strategies exist in allocations
        for strategy in config.strategies.active:
            if strategy not in config.strategies.allocations:
                issues.append(f"Active strategy '{strategy}' not found in allocations")
        
        return issues
    
    def validate_risk_parameters(self, config: CryptoAIBotConfig) -> List[str]:
        """Validate risk management parameters."""
        issues = []
        
        # Check risk limits are reasonable
        max_drawdown = config.risk.portfolio.get("max_drawdown_pct", 0)
        if max_drawdown > 50:
            issues.append(f"Max drawdown {max_drawdown}% is very high")
        
        # Check position limits
        max_position = config.risk.portfolio.get("max_single_position_notional_usd", 0)
        if max_position > 10000:
            issues.append(f"Max single position ${max_position} is very large")
        
        return issues
    
    def validate_performance_settings(self, config: CryptoAIBotConfig) -> List[str]:
        """Validate performance-related settings."""
        issues = []
        
        # Check Redis connection settings
        if not config.redis.url or config.redis.url == "${REDIS_URL}":
            issues.append("Redis URL not configured")
        
        # Check Discord webhook if enabled
        if config.discord.enabled and not config.discord.webhook_url:
            issues.append("Discord webhook URL not configured")
        
        return issues
    
    def validate_deployment_readiness(self, config: CryptoAIBotConfig) -> Dict[str, Any]:
        """Comprehensive deployment readiness validation."""
        strategy_issues = self.validate_strategy_consistency(config)
        risk_issues = self.validate_risk_parameters(config)
        performance_issues = self.validate_performance_settings(config)
        
        total_issues = len(strategy_issues) + len(risk_issues) + len(performance_issues)
        
        return {
            "valid": total_issues == 0,
            "deployment_ready": total_issues == 0,
            "strategy_issues": strategy_issues,
            "risk_issues": risk_issues,
            "performance_issues": performance_issues,
            "total_issues": total_issues
        }


# =============================================================================
# Main Functions
# =============================================================================

def load_and_validate_config(config_path: str = "config/settings.yaml") -> tuple[CryptoAIBotConfig, Dict[str, Any]]:
    """Load and validate configuration, returning config and validation report."""
    loader = ConfigLoader(config_path)
    config = loader.load_config()
    
    validator = ConfigValidator()
    validation_report = validator.validate_deployment_readiness(config)
    
    return config, validation_report


def validate_deployment(config_path: str = "config/settings.yaml") -> Dict[str, Any]:
    """Validate deployment readiness."""
    _, validation_report = load_and_validate_config(config_path)
    return validation_report
