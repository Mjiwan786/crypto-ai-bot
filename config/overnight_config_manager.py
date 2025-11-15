"""
Overnight Momentum Configuration Manager with Live Updates

Manages overnight momentum strategy configuration with:
- Environment variable overrides (env-first)
- Live updates via Redis streams
- Validation with bounds checking
- Fail-fast on invalid configurations
- Hot-reload without restarts

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import logging
import threading
import json
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, asdict, field
from decimal import Decimal
import yaml


@dataclass
class ValidationBounds:
    """Validation bounds for configuration parameters."""
    min: float
    max: float

    def validate(self, value: float, param_name: str) -> None:
        """
        Validate parameter is within bounds.

        Args:
            value: Parameter value to validate
            param_name: Parameter name for error messages

        Raises:
            ValueError: If value is out of bounds
        """
        if not (self.min <= value <= self.max):
            raise ValueError(
                f"{param_name} value {value} out of bounds [{self.min}, {self.max}]"
            )


@dataclass
class OvernightMomentumConfig:
    """Overnight Momentum Strategy Configuration."""
    # Feature Flags
    enabled: bool = False
    backtest_only: bool = True

    # Session
    asian_start_utc: int = 0
    asian_end_utc: int = 8

    # Entry Criteria
    volume_percentile_max: float = 50.0
    momentum_threshold: float = 0.6
    min_price_change_pct: float = 0.5
    min_volatility_expansion: float = 1.2

    # Targets & Risk
    target_min_pct: float = 1.0
    target_max_pct: float = 3.0
    default_target_pct: float = 1.5
    trailing_stop_pct: float = 0.7
    trailing_stop_min_pct: float = 0.5
    trailing_stop_max_pct: float = 1.0

    # Position Limits
    max_concurrent_positions: int = 1
    max_position_size_usd: float = 5000.0
    min_position_size_usd: float = 100.0

    # Leverage Proxy
    use_margin: bool = False
    spot_notional_multiplier: float = 2.0
    max_notional_multiplier: float = 3.0

    # Risk
    risk_per_trade_pct: float = 1.0
    use_atr_sizing: bool = False
    max_correlation: float = 0.7
    max_portfolio_heat_pct: float = 10.0

    # Exit
    session_end_exit: bool = True
    max_hold_hours: int = 8
    volatility_spike_threshold: float = 2.0
    drawdown_exit_pct: float = 2.0

    # Promotion Gates
    promotion_min_trades: int = 50
    promotion_min_win_rate: float = 0.55
    promotion_min_sharpe: float = 1.5
    promotion_max_drawdown: float = 0.10
    promotion_min_profit_factor: float = 1.5

    # Symbols
    symbol_whitelist: List[str] = field(default_factory=lambda: ["BTC/USD", "ETH/USD"])
    symbol_blacklist: List[str] = field(default_factory=lambda: ["SOL/USD"])

    # Monitoring
    alert_on_entry: bool = True
    alert_on_exit: bool = True
    alert_on_trailing_stop_update: bool = False
    log_level: str = "INFO"

    # Redis Streams
    publish_signals: bool = True
    publish_exits: bool = True
    signal_stream: str = "overnight:signals"
    exit_stream: str = "overnight:exits"
    position_stream: str = "overnight:positions"
    config_update_stream: str = "overnight:config_updates"
    audit_stream: str = "overnight:audit"

    # Audit
    log_all_decisions: bool = True
    audit_log_file: str = "logs/overnight_momentum_audit.log"

    # Validation Bounds
    validation_bounds: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "risk_per_trade_pct": {"min": 0.1, "max": 5.0},
        "trailing_stop_pct": {"min": 0.3, "max": 2.0},
        "target_pct": {"min": 0.5, "max": 5.0},
        "notional_multiplier": {"min": 1.0, "max": 3.0},
        "portfolio_heat_pct": {"min": 1.0, "max": 20.0},
        "volume_percentile_max": {"min": 10.0, "max": 90.0},
        "momentum_threshold": {"min": 0.1, "max": 1.0},
    })

    def validate(self) -> None:
        """
        Validate configuration parameters against bounds.

        Raises:
            ValueError: If any parameter is out of bounds
        """
        # Validate risk_per_trade_pct
        bounds = ValidationBounds(**self.validation_bounds["risk_per_trade_pct"])
        bounds.validate(self.risk_per_trade_pct, "risk_per_trade_pct")

        # Validate trailing_stop_pct
        bounds = ValidationBounds(**self.validation_bounds["trailing_stop_pct"])
        bounds.validate(self.trailing_stop_pct, "trailing_stop_pct")

        # Validate target percentages
        bounds = ValidationBounds(**self.validation_bounds["target_pct"])
        bounds.validate(self.target_min_pct, "target_min_pct")
        bounds.validate(self.target_max_pct, "target_max_pct")
        bounds.validate(self.default_target_pct, "default_target_pct")

        # Validate notional_multiplier
        bounds = ValidationBounds(**self.validation_bounds["notional_multiplier"])
        bounds.validate(self.spot_notional_multiplier, "spot_notional_multiplier")

        # Validate portfolio_heat_pct
        bounds = ValidationBounds(**self.validation_bounds["portfolio_heat_pct"])
        bounds.validate(self.max_portfolio_heat_pct, "max_portfolio_heat_pct")

        # Validate volume_percentile_max
        bounds = ValidationBounds(**self.validation_bounds["volume_percentile_max"])
        bounds.validate(self.volume_percentile_max, "volume_percentile_max")

        # Validate momentum_threshold
        bounds = ValidationBounds(**self.validation_bounds["momentum_threshold"])
        bounds.validate(self.momentum_threshold, "momentum_threshold")

        # Logical validations
        if self.target_min_pct > self.target_max_pct:
            raise ValueError("target_min_pct must be <= target_max_pct")

        if self.trailing_stop_pct > self.target_min_pct:
            raise ValueError("trailing_stop_pct should be < target_min_pct for positive expectancy")

        if self.use_margin:
            logging.warning("⚠️  MARGIN ENABLED for overnight positions (NOT RECOMMENDED)")


class OvernightConfigManager:
    """
    Overnight Momentum Configuration Manager with Live Updates.

    Features:
    - Environment variable overrides (env-first)
    - Live updates via Redis streams
    - Validation with fail-fast
    - Hot-reload without restarts
    - Change callbacks
    """

    def __init__(
        self,
        config_path: str = "config/enhanced_scalper_config.yaml",
        redis_manager=None,
        logger=None,
    ):
        """
        Initialize config manager.

        Args:
            config_path: Path to YAML configuration file
            redis_manager: Redis client for live updates
            logger: Logger instance
        """
        self.config_path = config_path
        self.redis = redis_manager
        self.logger = logger or logging.getLogger(__name__)

        # Current configuration
        self.config: Optional[OvernightMomentumConfig] = None

        # Change callbacks
        self.change_callbacks: List[Callable[[OvernightMomentumConfig], None]] = []

        # Redis stream monitoring
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Load initial configuration
        self.reload()

        # Start Redis stream monitoring if available
        if self.redis:
            self._start_stream_monitoring()

    def reload(self) -> None:
        """
        Reload configuration from YAML and environment variables.

        Environment variables take precedence over YAML (env-first).
        """
        try:
            # Load YAML config
            with open(self.config_path, 'r') as f:
                yaml_config = yaml.safe_load(f)

            # Extract overnight momentum config
            overnight_yaml = yaml_config.get('strategies', {}).get('overnight_momentum', {})

            # Build config with env-first overrides
            config_dict = self._build_config_with_env_overrides(overnight_yaml)

            # Create config object
            new_config = OvernightMomentumConfig(**config_dict)

            # Validate (fail-fast)
            new_config.validate()

            # Update if validation passed
            old_config = self.config
            self.config = new_config

            self.logger.info("Overnight momentum configuration reloaded successfully")

            # Trigger change callbacks if config changed
            if old_config and old_config != new_config:
                self._trigger_change_callbacks()
                self.logger.info("Configuration changed - callbacks triggered")

        except Exception as e:
            self.logger.error(f"Failed to reload configuration: {e}")
            raise

    def _build_config_with_env_overrides(self, yaml_config: Dict) -> Dict[str, Any]:
        """
        Build configuration dictionary with environment variable overrides.

        Environment variables take precedence (env-first).

        Args:
            yaml_config: YAML configuration dictionary

        Returns:
            Configuration dictionary with env overrides applied
        """
        config = {}

        # Feature flags
        config['enabled'] = self._get_env_bool('OVERNIGHT_MOMENTUM_ENABLED',
                                                yaml_config.get('enabled', False))
        config['backtest_only'] = self._get_env_bool('OVERNIGHT_BACKTEST_ONLY',
                                                      yaml_config.get('backtest_only', True))

        # Session
        session = yaml_config.get('session', {})
        config['asian_start_utc'] = session.get('asian_start_utc', 0)
        config['asian_end_utc'] = session.get('asian_end_utc', 8)

        # Entry criteria
        entry = yaml_config.get('entry', {})
        config['volume_percentile_max'] = self._get_env_float(
            'OVERNIGHT_VOLUME_PERCENTILE_MAX',
            entry.get('volume_percentile_max', 50.0)
        )
        config['momentum_threshold'] = self._get_env_float(
            'OVERNIGHT_MOMENTUM_THRESHOLD',
            entry.get('momentum_threshold', 0.6)
        )
        config['min_price_change_pct'] = entry.get('min_price_change_pct', 0.5)
        config['min_volatility_expansion'] = entry.get('min_volatility_expansion', 1.2)

        # Targets & Risk
        targets = yaml_config.get('targets', {})
        config['target_min_pct'] = self._get_env_float(
            'OVERNIGHT_TARGET_MIN',
            targets.get('target_min_pct', 1.0)
        )
        config['target_max_pct'] = self._get_env_float(
            'OVERNIGHT_TARGET_MAX',
            targets.get('target_max_pct', 3.0)
        )
        config['default_target_pct'] = self._get_env_float(
            'OVERNIGHT_TARGET_DEFAULT',
            targets.get('default_target_pct', 1.5)
        )
        config['trailing_stop_pct'] = self._get_env_float(
            'OVERNIGHT_TRAILING_STOP',
            targets.get('trailing_stop_pct', 0.7)
        )
        config['trailing_stop_min_pct'] = targets.get('trailing_stop_min_pct', 0.5)
        config['trailing_stop_max_pct'] = targets.get('trailing_stop_max_pct', 1.0)

        # Position limits
        limits = yaml_config.get('limits', {})
        config['max_concurrent_positions'] = limits.get('max_concurrent_positions', 1)
        config['max_position_size_usd'] = self._get_env_float(
            'OVERNIGHT_MAX_POSITION_USD',
            limits.get('max_position_size_usd', 5000.0)
        )
        config['min_position_size_usd'] = self._get_env_float(
            'OVERNIGHT_MIN_POSITION_USD',
            limits.get('min_position_size_usd', 100.0)
        )

        # Leverage proxy
        leverage = yaml_config.get('leverage', {})
        config['use_margin'] = self._get_env_bool(
            'OVERNIGHT_USE_MARGIN',
            leverage.get('use_margin', False)
        )
        config['spot_notional_multiplier'] = self._get_env_float(
            'OVERNIGHT_NOTIONAL_MULTIPLIER',
            leverage.get('spot_notional_multiplier', 2.0)
        )
        config['max_notional_multiplier'] = leverage.get('max_notional_multiplier', 3.0)

        # Risk
        risk = yaml_config.get('risk', {})
        config['risk_per_trade_pct'] = self._get_env_float(
            'OVERNIGHT_RISK_PER_TRADE',
            risk.get('risk_per_trade_pct', 1.0)
        )
        config['use_atr_sizing'] = risk.get('use_atr_sizing', False)
        config['max_correlation'] = risk.get('max_correlation', 0.7)
        config['max_portfolio_heat_pct'] = self._get_env_float(
            'OVERNIGHT_MAX_PORTFOLIO_HEAT',
            risk.get('max_portfolio_heat_pct', 10.0)
        )

        # Exit
        exit_cfg = yaml_config.get('exit', {})
        config['session_end_exit'] = exit_cfg.get('session_end_exit', True)
        config['max_hold_hours'] = exit_cfg.get('max_hold_hours', 8)
        config['volatility_spike_threshold'] = exit_cfg.get('volatility_spike_threshold', 2.0)
        config['drawdown_exit_pct'] = exit_cfg.get('drawdown_exit_pct', 2.0)

        # Promotion gates
        gates = yaml_config.get('promotion_gates', {})
        config['promotion_min_trades'] = self._get_env_int(
            'OVERNIGHT_PROMOTION_MIN_TRADES',
            gates.get('min_trades', 50)
        )
        config['promotion_min_win_rate'] = self._get_env_float(
            'OVERNIGHT_PROMOTION_MIN_WIN_RATE',
            gates.get('min_win_rate', 0.55)
        )
        config['promotion_min_sharpe'] = self._get_env_float(
            'OVERNIGHT_PROMOTION_MIN_SHARPE',
            gates.get('min_sharpe', 1.5)
        )
        config['promotion_max_drawdown'] = self._get_env_float(
            'OVERNIGHT_PROMOTION_MAX_DRAWDOWN',
            gates.get('max_drawdown', 0.10)
        )
        config['promotion_min_profit_factor'] = gates.get('min_profit_factor', 1.5)

        # Symbols
        symbols = yaml_config.get('symbols', {})
        config['symbol_whitelist'] = symbols.get('whitelist', ["BTC/USD", "ETH/USD"])
        config['symbol_blacklist'] = symbols.get('blacklist', ["SOL/USD"])

        # Monitoring
        monitoring = yaml_config.get('monitoring', {})
        config['alert_on_entry'] = monitoring.get('alert_on_entry', True)
        config['alert_on_exit'] = monitoring.get('alert_on_exit', True)
        config['alert_on_trailing_stop_update'] = monitoring.get('alert_on_trailing_stop_update', False)
        config['log_level'] = self._get_env_str(
            'OVERNIGHT_LOG_LEVEL',
            monitoring.get('log_level', 'INFO')
        )

        # Redis streams
        redis_cfg = yaml_config.get('redis', {})
        config['publish_signals'] = redis_cfg.get('publish_signals', True)
        config['publish_exits'] = redis_cfg.get('publish_exits', True)
        config['signal_stream'] = redis_cfg.get('signal_stream', 'overnight:signals')
        config['exit_stream'] = redis_cfg.get('exit_stream', 'overnight:exits')
        config['position_stream'] = redis_cfg.get('position_stream', 'overnight:positions')
        config['config_update_stream'] = redis_cfg.get('config_update_stream', 'overnight:config_updates')
        config['audit_stream'] = redis_cfg.get('audit_stream', 'overnight:audit')

        # Audit
        audit = yaml_config.get('audit', {})
        config['log_all_decisions'] = audit.get('log_all_decisions', True)
        config['audit_log_file'] = audit.get('log_file', 'logs/overnight_momentum_audit.log')

        # Validation bounds (only include if present in YAML, else use dataclass defaults)
        validation_bounds = yaml_config.get('validation_bounds', None)
        if validation_bounds:
            config['validation_bounds'] = validation_bounds

        return config

    def _get_env_bool(self, env_var: str, default: bool) -> bool:
        """Get boolean from environment variable."""
        value = os.getenv(env_var)
        if value is None:
            return default
        return value.lower() in ('true', '1', 'yes', 'on')

    def _get_env_int(self, env_var: str, default: int) -> int:
        """Get integer from environment variable."""
        value = os.getenv(env_var)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            self.logger.warning(f"Invalid int for {env_var}: {value}, using default {default}")
            return default

    def _get_env_float(self, env_var: str, default: float) -> float:
        """Get float from environment variable."""
        value = os.getenv(env_var)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            self.logger.warning(f"Invalid float for {env_var}: {value}, using default {default}")
            return default

    def _get_env_str(self, env_var: str, default: str) -> str:
        """Get string from environment variable."""
        return os.getenv(env_var, default)

    def get_config(self) -> OvernightMomentumConfig:
        """Get current configuration."""
        if self.config is None:
            raise RuntimeError("Configuration not loaded")
        return self.config

    def update_config(self, updates: Dict[str, Any]) -> None:
        """
        Update configuration with new values.

        Validates before applying updates.

        Args:
            updates: Dictionary of configuration updates

        Raises:
            ValueError: If updated configuration is invalid
        """
        if self.config is None:
            raise RuntimeError("Configuration not loaded")

        # Create updated config
        current_dict = asdict(self.config)
        current_dict.update(updates)
        new_config = OvernightMomentumConfig(**current_dict)

        # Validate (fail-fast)
        new_config.validate()

        # Apply if validation passed
        self.config = new_config

        # Publish update to Redis
        if self.redis:
            self._publish_config_update(updates)

        # Trigger callbacks
        self._trigger_change_callbacks()

        self.logger.info(f"Configuration updated: {list(updates.keys())}")

    def register_change_callback(self, callback: Callable[[OvernightMomentumConfig], None]) -> None:
        """
        Register callback for configuration changes.

        Args:
            callback: Function to call when configuration changes
        """
        self.change_callbacks.append(callback)

    def _trigger_change_callbacks(self) -> None:
        """Trigger all registered change callbacks."""
        for callback in self.change_callbacks:
            try:
                callback(self.config)
            except Exception as e:
                self.logger.error(f"Error in config change callback: {e}")

    def _start_stream_monitoring(self) -> None:
        """Start Redis stream monitoring for live updates."""
        if not self.redis:
            return

        self._stream_thread = threading.Thread(
            target=self._monitor_config_stream,
            daemon=True,
            name="overnight_config_stream_monitor"
        )
        self._stream_thread.start()
        self.logger.info("Overnight config stream monitoring started")

    def _monitor_config_stream(self) -> None:
        """Monitor Redis stream for configuration updates."""
        stream_name = self.config.config_update_stream if self.config else "overnight:config_updates"
        last_id = "0"

        while not self._stop_event.is_set():
            try:
                # Read from stream
                messages = self.redis.xread({stream_name: last_id}, count=10, block=1000)

                for stream, entries in messages:
                    for msg_id, data in entries:
                        last_id = msg_id
                        self._process_config_update(data)

            except Exception as e:
                self.logger.error(f"Error monitoring config stream: {e}")
                time.sleep(1)

    def _process_config_update(self, data: Dict[str, bytes]) -> None:
        """
        Process configuration update from Redis stream.

        Args:
            data: Configuration update data from stream
        """
        try:
            # Decode data
            updates = {}
            for key, value in data.items():
                if isinstance(value, bytes):
                    value = value.decode('utf-8')

                # Try to parse as JSON
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    # Try to convert to appropriate type
                    if value.lower() in ('true', 'false'):
                        value = value.lower() == 'true'
                    else:
                        try:
                            value = float(value)
                        except ValueError:
                            pass  # Keep as string

                updates[key.decode('utf-8') if isinstance(key, bytes) else key] = value

            # Apply updates
            self.update_config(updates)

            self.logger.info(f"Applied live config update: {list(updates.keys())}")

        except Exception as e:
            self.logger.error(f"Failed to process config update: {e}")

    def _publish_config_update(self, updates: Dict[str, Any]) -> None:
        """
        Publish configuration update to Redis stream.

        Args:
            updates: Configuration updates to publish
        """
        if not self.redis or not self.config:
            return

        try:
            # Prepare data for stream
            data = {
                "timestamp": time.time(),
                "source": "overnight_config_manager",
                "updates": json.dumps(updates)
            }

            # Add individual fields
            for key, value in updates.items():
                data[key] = json.dumps(value) if not isinstance(value, (str, int, float, bool)) else str(value)

            # Publish to stream
            self.redis.xadd(self.config.config_update_stream, data)

        except Exception as e:
            self.logger.error(f"Failed to publish config update: {e}")

    def stop(self) -> None:
        """Stop configuration manager."""
        self._stop_event.set()
        if self._stream_thread:
            self._stream_thread.join(timeout=2.0)
        self.logger.info("Overnight configuration manager stopped")

    def get_status(self) -> Dict[str, Any]:
        """Get configuration manager status."""
        return {
            "config_loaded": self.config is not None,
            "stream_monitoring": self._stream_thread and self._stream_thread.is_alive() if self.redis else False,
            "change_callbacks": len(self.change_callbacks),
            "config_path": str(self.config_path),
            "enabled": self.config.enabled if self.config else False,
            "backtest_only": self.config.backtest_only if self.config else True,
        }


def create_overnight_config_manager(
    config_path: str = "config/enhanced_scalper_config.yaml",
    redis_manager=None,
    logger=None,
) -> OvernightConfigManager:
    """
    Create overnight configuration manager.

    Args:
        config_path: Path to YAML configuration
        redis_manager: Redis client for live updates
        logger: Logger instance

    Returns:
        OvernightConfigManager instance
    """
    return OvernightConfigManager(
        config_path=config_path,
        redis_manager=redis_manager,
        logger=logger,
    )
