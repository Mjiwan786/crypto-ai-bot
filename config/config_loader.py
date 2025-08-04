# config/config_loader.py
import yaml
import os
from types import SimpleNamespace
from typing import Union, Dict, Any, List
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "strategies": {
        "active_strategies": ["trend_following", "breakout"],
        "allocations": {
            "trend_following": 0.25,
            "breakout": 0.20,
            "mean_reversion": 0.15,
            "momentum": 0.25,
            "sideways": 0.15
        }
    },
    "trading": {
        "base_position_size": 0.15,
        "dynamic_sizing": {
            "enabled": True,
            "volatility_multiplier": 1.8,
            "max_position": 0.30
        }
    }
}

def dict_to_namespace(data: Union[Dict, List]) -> Any:
    """Recursively convert dictionaries to SimpleNamespace objects."""
    if isinstance(data, dict):
        return SimpleNamespace(**{k: dict_to_namespace(v) for k, v in data.items()})
    elif isinstance(data, list):
        return [dict_to_namespace(item) for item in data]
    return data

def load_settings(file_path: str = "config/settings.yaml") -> SimpleNamespace:
    """
    Load and validate configuration with these features:
    - Dot notation access (config.strategies.active_strategies)
    - Environment variable overrides
    - Default values for missing keys
    - Automatic YAML validation
    """
    try:
        # Load YAML file
        if not os.path.exists(file_path):
            logger.warning(f"Config file not found at {file_path}, using defaults")
            return dict_to_namespace(DEFAULT_CONFIG)

        with open(file_path) as f:
            config = yaml.safe_load(f) or {}

        # Deep merge with defaults
        def deep_merge(default, override):
            for key, value in override.items():
                if isinstance(value, dict) and key in default:
                    deep_merge(default[key], value)
                else:
                    default[key] = value
            return default

        config = deep_merge(DEFAULT_CONFIG.copy(), config)

        # Environment variable overrides
        for env_key, env_value in os.environ.items():
            if env_key.startswith("BOT_"):
                keys = env_key[4:].lower().split('__')  # BOT_STRATEGIES__ACTIVE_STRATEGIES
                current = config
                for key in keys[:-1]:
                    current = current.setdefault(key, {})
                current[keys[-1]] = type(current[keys[-1]])(env_value) if keys[-1] in current else env_value

        # Convert to namespace object
        config_obj = dict_to_namespace(config)

        # Post-load validation
        if not hasattr(config_obj, 'strategies') or not hasattr(config_obj.strategies, 'active_strategies'):
            raise ValueError("Missing required strategies.active_strategies in config")

        logger.info("Configuration loaded successfully")
        return config_obj

    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in config file: {str(e)}")
        return dict_to_namespace(DEFAULT_CONFIG)
    except Exception as e:
        logger.error(f"Config loading failed: {str(e)}")
        return dict_to_namespace(DEFAULT_CONFIG)

# Test cases
if __name__ == "__main__":
    # Test loading
    config = load_settings()
    print(f"Active strategies: {config.strategies.active_strategies}")
    print(f"Base position size: {config.trading.base_position_size}")

    # Test environment override
    os.environ["BOT_TRADING__BASE_POSITION_SIZE"] = "0.20"
    config = load_settings()
    print(f"Modified position size: {config.trading.base_position_size}")