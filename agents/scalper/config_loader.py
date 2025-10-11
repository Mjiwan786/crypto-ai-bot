# agents/scalper/config_loader.py
"""
Scalper-specific configuration loader that integrates with the main configuration system.
Handles scalping strategy parameters, Kraken-specific settings, and validation.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# --- Pydantic v1/v2 compatibility shims --------------------------------------
try:
    from pydantic import BaseModel, Field

    try:
        # v2
        from pydantic import field_validator as _field_validator  # type: ignore

        _V2 = True

        def field_validator(*args, **kwargs):
            return _field_validator(*args, **kwargs)

    except Exception:
        # v1
        from pydantic import validator as field_validator  # type: ignore

        _V2 = False
except Exception as _e:  # pragma: no cover
    raise ImportError("pydantic is required for scalper config loader") from _e

# Import main configuration system (your enhanced loader that the agents expect)
from config.loader import CryptoAIBotConfig, get_config

# =============================================================================
# Enumerations
# =============================================================================


class ScalpingMode(str, Enum):
    """Scalping operating modes"""

    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"
    ADAPTIVE = "adaptive"


class LiquidityRequirement(str, Enum):
    """Liquidity requirement levels"""

    MINIMAL = "minimal"
    STANDARD = "standard"
    HIGH = "high"
    ULTRA_HIGH = "ultra_high"


# =============================================================================
# Pydantic models
# =============================================================================


class ScalpingPairConfig(BaseModel):
    """Configuration for individual trading pair"""

    symbol: str
    enabled: bool = True
    min_order_size_usd: float = Field(default=25.0, gt=0)
    max_order_size_usd: float = Field(default=500.0, gt=0)
    target_profit_bps: int = Field(default=10, ge=3, le=50)
    stop_loss_bps: int = Field(default=5, ge=1, le=25)
    max_spread_bps: float = Field(default=3.0, gt=0, le=20)
    min_liquidity_usd: float = Field(default=100_000.0, gt=0)

    # Kraken-specific settings
    price_precision: int = Field(default=1, ge=0)
    size_precision: int = Field(default=8, ge=0)
    min_order_kraken: float = Field(default=0.002, gt=0)

    @field_validator("max_order_size_usd")
    def _max_gt_min(cls, v, info):  # type: ignore[override]
        data = info.data if hasattr(info, "data") else {}
        min_v = data.get("min_order_size_usd")
        if min_v is not None and v <= float(min_v):
            raise ValueError("max_order_size_usd must be greater than min_order_size_usd")
        return v

    @field_validator("target_profit_bps")
    def _tp_gt_sl(cls, v, info):  # type: ignore[override]
        data = info.data if hasattr(info, "data") else {}
        sl = data.get("stop_loss_bps")
        if sl is not None and int(v) <= int(sl):
            raise ValueError("target_profit_bps must be greater than stop_loss_bps")
        return v


class ScalpingRiskConfig(BaseModel):
    """Risk management configuration for scalping"""

    max_trades_per_minute: int = Field(default=4, ge=1, le=20)
    max_trades_per_hour: int = Field(default=60, ge=1, le=300)
    max_trades_per_day: int = Field(default=150, ge=1, le=1000)

    # Position limits
    max_concurrent_positions: int = Field(default=2, ge=1, le=5)
    max_total_exposure_percent: float = Field(default=0.25, gt=0, le=1.0)
    max_single_position_percent: float = Field(default=0.10, gt=0, le=0.5)

    # Loss limits
    daily_loss_limit_percent: float = Field(default=-0.02, ge=-0.1, le=0)
    consecutive_loss_limit: int = Field(default=3, ge=1, le=10)
    cooldown_after_loss_seconds: int = Field(default=90, ge=30, le=600)

    # Drawdown protection
    max_drawdown_percent: float = Field(default=-0.05, ge=-0.2, le=0)
    drawdown_pause_threshold: float = Field(default=-0.03, ge=-0.1, le=0)


class ScalpingExecutionConfig(BaseModel):
    """Execution configuration for scalping"""

    order_type_preference: str = Field(default="limit", pattern="^(limit|market)$")
    time_in_force: str = Field(default="GTC", pattern="^(GTC|IOC|FOK)$")
    post_only_preference: bool = True
    hidden_orders_preference: bool = True

    # Timing parameters
    max_order_lifetime_seconds: int = Field(default=120, ge=30, le=600)
    order_update_threshold_bps: float = Field(default=2.0, ge=0.5, le=10)
    execution_timeout_ms: int = Field(default=5000, ge=1000, le=30000)

    # Slippage and fill management
    max_acceptable_slippage_bps: float = Field(default=4.0, ge=1, le=20)
    partial_fill_threshold: float = Field(default=0.8, gt=0, le=1.0)
    cancel_replace_enabled: bool = True

    @field_validator("time_in_force")
    def _kraken_tif_guard(cls, v):  # type: ignore[override]
        # Kraken spot supports only GTC (matches your MCP OrderIntent guard)
        if v != "GTC":
            raise ValueError("Kraken spot supports only GTC time_in_force")
        return v


class ScalpingMarketConfig(BaseModel):
    """Market condition requirements for scalping"""

    liquidity_requirement: LiquidityRequirement = LiquidityRequirement.STANDARD

    # Book depth requirements
    min_book_depth_levels: int = Field(default=10, ge=3, le=50)
    min_bid_depth_usd: float = Field(default=50_000.0, gt=0)
    min_ask_depth_usd: float = Field(default=50_000.0, gt=0)

    # Market quality thresholds
    min_book_balance_ratio: float = Field(default=0.65, ge=0.5, le=1.0)
    max_spread_volatility: float = Field(default=2.0, gt=0)
    min_trade_frequency_per_minute: int = Field(default=5, ge=1)

    # Volatility windows
    volatility_lookback_minutes: int = Field(default=15, ge=5, le=60)
    max_volatility_threshold: float = Field(default=0.05, gt=0, le=0.5)


class ScalpingPerformanceConfig(BaseModel):
    """Performance monitoring and optimization"""

    # Latency requirements
    max_acceptable_latency_ms: float = Field(default=150.0, gt=0, le=1000)
    latency_monitoring_enabled: bool = True

    # Performance tracking
    win_rate_monitoring_window_minutes: int = Field(default=60, ge=15, le=240)
    min_acceptable_win_rate: float = Field(default=0.55, ge=0.5, le=1.0)

    # Strategy adaptation
    adaptive_parameters_enabled: bool = True
    performance_review_interval_minutes: int = Field(default=30, ge=10, le=120)
    auto_pause_on_poor_performance: bool = True


class KrakenScalpingConfig(BaseModel):
    """Complete Kraken scalping configuration"""

    # Strategy identification
    strategy_name: str = "kraken_scalp"
    version: str = "1.0.0"
    enabled: bool = True
    mode: ScalpingMode = ScalpingMode.CONSERVATIVE

    # Timeframe and frequency
    primary_timeframe: str = Field(default="15s", pattern="^(15s|30s|1m)$")
    analysis_frequency_ms: int = Field(default=500, ge=100, le=5000)

    # Component configurations
    pairs: Dict[str, ScalpingPairConfig]
    risk: ScalpingRiskConfig
    execution: ScalpingExecutionConfig
    market: ScalpingMarketConfig
    performance: ScalpingPerformanceConfig

    # Kraken-specific settings
    kraken_api_settings: Dict[str, Any] = Field(default_factory=dict)

    # Feature flags
    features: Dict[str, bool] = Field(
        default_factory=lambda: {
            "order_book_analysis": True,
            "microstructure_signals": True,
            "adaptive_sizing": True,
            "smart_routing": True,
            "latency_optimization": True,
        }
    )

    @field_validator("pairs")
    def _at_least_one_enabled_pair(cls, v):  # type: ignore[override]
        if not any(pair.enabled for pair in v.values()):
            raise ValueError("At least one trading pair must be enabled")
        return v


# =============================================================================
# Loader
# =============================================================================


class ScalperConfigLoader:
    """
    Configuration loader specifically for the Kraken scalper agent.
    Integrates with the main configuration system while providing
    scalper-specific validation and defaults.
    """

    def __init__(self, scalper_config_path: Optional[str] = None):
        self.logger = logging.getLogger("scalper.config")

        # Determine config paths
        self.scalper_config_path = scalper_config_path or self._get_default_scalper_config_path()

        # Load main configuration
        self.main_config: CryptoAIBotConfig = get_config()

        # Cache for loaded scalper config
        self._scalper_config: Optional[KrakenScalpingConfig] = None

    # ---------- pathing ----------
    def _get_default_scalper_config_path(self) -> str:
        """Get default path for scalper configuration"""
        base_paths = [
            "agents/scalper/config/settings.yaml",
            "config/scalping_settings.yaml",
            "scalping_settings.yaml",
        ]
        for path in base_paths:
            if Path(path).exists():
                return path
        return base_paths[0]

    # ---------- public API ----------
    def load_scalper_config(self) -> KrakenScalpingConfig:
        """
        Load and validate scalper configuration.
        Combines main config with scalper-specific settings.
        """
        try:
            # Load scalper-specific config if it exists
            scalper_dict: Dict[str, Any] = {}
            if Path(self.scalper_config_path).exists():
                scalper_dict = self._load_yaml_config(self.scalper_config_path)
            else:
                self.logger.info(
                    f"No scalper config file found at {self.scalper_config_path}, using defaults + main config"
                )

            # Extract scalping settings from main config
            main_scalp_config = self._extract_from_main_config()

            # Merge configurations (scalper-specific overrides main config)
            merged_config = self._merge_configs(main_scalp_config, scalper_dict)

            # Create and validate scalper configuration
            self._scalper_config = KrakenScalpingConfig(**merged_config)

            # Additional validation
            self._validate_scalper_config(self._scalper_config)

            self.logger.info("Scalper configuration loaded successfully")
            enabled = [s for s, c in self._scalper_config.pairs.items() if c.enabled]
            self.logger.debug(f"Enabled pairs: {enabled}")

            return self._scalper_config

        except Exception as e:
            self.logger.error(f"Failed to load scalper configuration: {e}", exc_info=e)
            raise

    def get_config(self) -> KrakenScalpingConfig:
        """Get cached scalper configuration or load it"""
        if self._scalper_config is None:
            self._scalper_config = self.load_scalper_config()
        return self._scalper_config

    def reload_config(self) -> KrakenScalpingConfig:
        """Force reload of scalper configuration"""
        self._scalper_config = None
        return self.load_scalper_config()

    # ---------- validators & helpers ----------
    def _load_yaml_config(self, path: str) -> Dict[str, Any]:
        """Load YAML configuration file with ${ENV[:-default]} substitution"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            return self._substitute_env_vars(raw)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {path}: {e}")
        except FileNotFoundError:
            raise FileNotFoundError(f"Scalper config file not found: {path}")

    def _substitute_env_vars(self, data: Any) -> Any:
        """Recursively substitute environment variables."""
        if isinstance(data, dict):
            return {k: self._substitute_env_vars(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._substitute_env_vars(x) for x in data]
        if isinstance(data, str) and data.startswith("${") and data.endswith("}"):
            # ${ENV} or ${ENV:-default}
            expr = data[2:-1]
            if ":-" in expr:
                env_name, default = expr.split(":-", 1)
                return os.getenv(env_name.strip(), default.strip())
            return os.getenv(expr.strip(), "")
        return data

    def _extract_from_main_config(self) -> Dict[str, Any]:
        """Extract scalping-relevant settings from main configuration"""
        cfg = self.main_config
        out: Dict[str, Any] = {}

        # Strategy (if present)
        scalp_cfg = getattr(getattr(cfg, "strategies", None), "scalp", None)
        if scalp_cfg:
            out.update(
                {
                    "enabled": getattr(scalp_cfg, "enabled", True),
                    "primary_timeframe": getattr(scalp_cfg, "timeframe", "15s"),
                }
            )

            # Risk settings
            out["risk"] = {
                "max_trades_per_minute": getattr(scalp_cfg, "max_trades_per_minute", 4),
                "max_trades_per_hour": getattr(scalp_cfg, "max_trades_per_hour", 60),
                "daily_loss_limit_percent": getattr(scalp_cfg, "daily_loss_limit_percent", -0.02),
                "cooldown_after_loss_seconds": getattr(
                    scalp_cfg, "cooldown_after_loss_seconds", 90
                ),
            }

            # Execution settings (normalize to Kraken GTC)
            out["execution"] = {
                "post_only_preference": getattr(scalp_cfg, "post_only", True),
                "hidden_orders_preference": getattr(scalp_cfg, "hidden_orders", True),
                "max_order_lifetime_seconds": getattr(scalp_cfg, "max_hold_seconds", 120),
                "time_in_force": "GTC",  # force Kraken constraint
            }

            # Market settings
            out["market"] = {
                "min_book_depth_levels": getattr(scalp_cfg, "min_book_depth_levels", 10),
                "max_spread_volatility": getattr(scalp_cfg, "max_spread_bps", 3.0),
            }

            # Pair configurations
            pairs_cfg: Dict[str, Any] = {}
            scalp_pairs = getattr(scalp_cfg, "pairs", ["BTC/USD", "ETH/USD"])
            pair_configs = getattr(scalp_cfg, "pair_configs", {}) or {}
            default_target = getattr(scalp_cfg, "target_bps", 10)
            default_sl = getattr(scalp_cfg, "stop_loss_bps", 5)
            default_spread = getattr(scalp_cfg, "max_spread_bps", 3.0)

            for symbol in scalp_pairs:
                pc = pair_configs.get(symbol, {}) or {}
                pairs_cfg[symbol] = {
                    "symbol": symbol,
                    "enabled": True,
                    "min_order_size_usd": pc.get("min_position_usd", 25.0),
                    "max_order_size_usd": pc.get("max_position_usd", 500.0),
                    "target_profit_bps": pc.get("target_bps", default_target),
                    "stop_loss_bps": default_sl,
                    "max_spread_bps": default_spread,
                }
            out["pairs"] = pairs_cfg

        # Exchanges (kraken)
        exchanges = getattr(cfg, "exchanges", None)
        if isinstance(exchanges, dict) and "kraken" in exchanges:
            kraken_cfg = exchanges["kraken"]
            out["kraken_api_settings"] = {
                "api_key": getattr(kraken_cfg, "api_key", None),
                "api_secret": getattr(kraken_cfg, "api_secret", None),
                "sandbox": getattr(kraken_cfg, "sandbox", False),
                "rate_limit_guard": getattr(kraken_cfg, "rate_limit_guard", True),
                "fee_maker": getattr(kraken_cfg, "fee_maker", 0.0016),
                "fee_taker": getattr(kraken_cfg, "fee_taker", 0.0026),
            }

        # Global risk (if present)
        risk = getattr(cfg, "risk", None)
        if risk:
            out.setdefault("risk", {})
            out["risk"].update(
                {
                    "max_concurrent_positions": getattr(risk, "max_concurrent_positions", 2),
                    "max_total_exposure_percent": getattr(risk, "per_symbol_max_exposure", 0.25),
                    "max_drawdown_percent": getattr(risk, "global_max_drawdown", -0.05),
                }
            )

        return out

    def _merge_configs(
        self, main_config: Dict[str, Any], scalper_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge defaults <- main <- scalper.yaml (override order)"""

        def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
            result = dict(base)
            for key, value in override.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = deep_merge(result[key], value)
                else:
                    result[key] = value
            return result

        merged = self._get_default_config()
        merged = deep_merge(merged, main_config or {})
        merged = deep_merge(merged, scalper_config or {})

        # Coerce enums if provided as strings in YAML
        if isinstance(merged.get("mode"), str):
            merged["mode"] = ScalpingMode(merged["mode"])
        lr = merged.get("market", {}).get("liquidity_requirement")
        if isinstance(lr, str):
            merged["market"]["liquidity_requirement"] = LiquidityRequirement(lr)
        return merged

    def _get_default_config(self) -> Dict[str, Any]:
        """Default scalper configuration (sane, Kraken-aligned)."""
        return {
            "strategy_name": "kraken_scalp",
            "version": "1.0.0",
            "enabled": True,
            "mode": ScalpingMode.CONSERVATIVE.value,
            "primary_timeframe": "15s",
            "analysis_frequency_ms": 500,
            "pairs": {
                "BTC/USD": {
                    "symbol": "BTC/USD",
                    "enabled": True,
                    "min_order_size_usd": 25.0,
                    "max_order_size_usd": 500.0,
                    "target_profit_bps": 10,
                    "stop_loss_bps": 5,
                    "max_spread_bps": 3.0,
                    "min_liquidity_usd": 100_000.0,
                    "price_precision": 1,
                    "size_precision": 8,
                    "min_order_kraken": 0.002,
                },
                "ETH/USD": {
                    "symbol": "ETH/USD",
                    "enabled": True,
                    "min_order_size_usd": 20.0,
                    "max_order_size_usd": 400.0,
                    "target_profit_bps": 12,
                    "stop_loss_bps": 6,
                    "max_spread_bps": 4.0,
                    "min_liquidity_usd": 80_000.0,
                    "price_precision": 2,
                    "size_precision": 7,
                    "min_order_kraken": 0.02,
                },
            },
            "risk": {
                "max_trades_per_minute": 4,
                "max_trades_per_hour": 60,
                "max_trades_per_day": 150,
                "max_concurrent_positions": 2,
                "max_total_exposure_percent": 0.25,
                "max_single_position_percent": 0.10,
                "daily_loss_limit_percent": -0.02,
                "consecutive_loss_limit": 3,
                "cooldown_after_loss_seconds": 90,
                "max_drawdown_percent": -0.05,
                "drawdown_pause_threshold": -0.03,
            },
            "execution": {
                "order_type_preference": "limit",
                "time_in_force": "GTC",  # Kraken spot only
                "post_only_preference": True,
                "hidden_orders_preference": True,
                "max_order_lifetime_seconds": 120,
                "order_update_threshold_bps": 2.0,
                "execution_timeout_ms": 5000,
                "max_acceptable_slippage_bps": 4.0,
                "partial_fill_threshold": 0.8,
                "cancel_replace_enabled": True,
            },
            "market": {
                "liquidity_requirement": LiquidityRequirement.STANDARD.value,
                "min_book_depth_levels": 10,
                "min_bid_depth_usd": 50_000.0,
                "min_ask_depth_usd": 50_000.0,
                "min_book_balance_ratio": 0.65,
                "max_spread_volatility": 2.0,
                "min_trade_frequency_per_minute": 5,
                "volatility_lookback_minutes": 15,
                "max_volatility_threshold": 0.05,
            },
            "performance": {
                "max_acceptable_latency_ms": 150.0,
                "latency_monitoring_enabled": True,
                "win_rate_monitoring_window_minutes": 60,
                "min_acceptable_win_rate": 0.55,
                "adaptive_parameters_enabled": True,
                "performance_review_interval_minutes": 30,
                "auto_pause_on_poor_performance": True,
            },
            "kraken_api_settings": {},
            "features": {
                "order_book_analysis": True,
                "microstructure_signals": True,
                "adaptive_sizing": True,
                "smart_routing": True,
                "latency_optimization": True,
            },
        }

    def _validate_scalper_config(self, config: KrakenScalpingConfig):
        """Perform additional validation on scalper configuration"""
        # Basic: at least one enabled pair is already guarded by model validator

        # Rate limits sanity
        if config.risk.max_trades_per_minute * 60 > config.risk.max_trades_per_hour:
            raise ValueError("max_trades_per_hour must accommodate max_trades_per_minute")

        # Risk/reward hints
        for symbol, pair in config.pairs.items():
            if not pair.enabled:
                continue
            rr = pair.target_profit_bps / max(1, pair.stop_loss_bps)
            if rr < 1.5:
                self.logger.warning(
                    f"Low risk/reward ratio for {symbol}: {rr:.2f} "
                    f"(target={pair.target_profit_bps}, stop={pair.stop_loss_bps})"
                )

        # Kraken API presence
        k = config.kraken_api_settings or {}
        if not k.get("api_key") or not k.get("api_secret"):
            raise ValueError("Kraken API credentials are required for scalping")

        # Execution TIF guard (already enforced in model)
        if config.execution.time_in_force != "GTC":
            raise ValueError("time_in_force must be GTC for Kraken spot")

        # Summary logs
        self.logger.info("Scalper configuration validated:")
        self.logger.info(f"  Mode: {config.mode.value}")
        self.logger.info(f"  Enabled pairs: {len([p for p in config.pairs.values() if p.enabled])}")
        self.logger.info(f"  Max trades/minute: {config.risk.max_trades_per_minute}")
        self.logger.info(f"  Primary timeframe: {config.primary_timeframe}")

    # ---------- runtime checks ----------
    def validate_runtime_config(self, config: KrakenScalpingConfig) -> List[str]:
        """Validate configuration for runtime issues (warnings, non-fatal)."""
        issues: List[str] = []

        if config.risk.max_trades_per_minute > 10:
            issues.append("Very high trade frequency may exceed Kraken rate limits")

        if config.analysis_frequency_ms < 100:
            issues.append("Very high analysis frequency may cause performance issues")

        for symbol, pair in config.pairs.items():
            if pair.enabled and pair.max_spread_bps < 2.0:
                issues.append(
                    f"Very tight spread requirement for {symbol} may reduce trading opportunities"
                )

        # crude fee sanity (round trip maker ~16 bps x2)
        kraken_fee_bps = 16
        for symbol, pair in config.pairs.items():
            if pair.enabled:
                net_profit = pair.target_profit_bps - (kraken_fee_bps * 2)
                if net_profit < 5:
                    issues.append(
                        f"Low net profit expectation for {symbol} after fees: {net_profit} bps"
                    )

        return issues


# =============================================================================
# Convenience functions
# =============================================================================


def load_scalper_config(config_path: Optional[str] = None) -> KrakenScalpingConfig:
    """
    Load scalper configuration.
    This is the main function that KrakenScalperAgent uses.
    """
    loader = ScalperConfigLoader(config_path)
    return loader.load_scalper_config()


def get_scalper_config_loader(config_path: Optional[str] = None) -> ScalperConfigLoader:
    """Get scalper configuration loader instance"""
    return ScalperConfigLoader(config_path)


def validate_scalper_deployment(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Validate scalper configuration for deployment"""
    try:
        loader = ScalperConfigLoader(config_path)
        config = loader.load_scalper_config()
        runtime_issues = loader.validate_runtime_config(config)
        return {
            "valid": True,
            "deployment_ready": len(runtime_issues) == 0,
            "issues": runtime_issues,
            "enabled_pairs": [symbol for symbol, pair in config.pairs.items() if pair.enabled],
            "mode": config.mode.value,
            "risk_settings": {
                "max_trades_per_minute": config.risk.max_trades_per_minute,
                "daily_loss_limit": config.risk.daily_loss_limit_percent,
                "max_exposure": config.risk.max_total_exposure_percent,
            },
        }
    except Exception as e:
        return {"valid": False, "deployment_ready": False, "error": str(e)}


__all__ = [
    "KrakenScalpingConfig",
    "ScalpingPairConfig",
    "ScalpingRiskConfig",
    "ScalpingExecutionConfig",
    "ScalpingMarketConfig",
    "ScalpingPerformanceConfig",
    "ScalpingMode",
    "LiquidityRequirement",
    "ScalperConfigLoader",
    "load_scalper_config",
    "get_scalper_config_loader",
    "validate_scalper_deployment",
]
