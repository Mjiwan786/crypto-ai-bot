"""
Microstructure configuration loader for liquidity and timing filters.

Loads microstructure filter configuration from YAML and converts to
MicrostructureConfig for use with MicrostructureGate.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

# Import microstructure classes
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.microstructure import (
    MicrostructureConfig,
    PairLiquidityConfig,
    TimeWindowConfig,
)

logger = logging.getLogger(__name__)


class PairConfigYAML(BaseModel):
    """Pair-specific liquidity configuration from YAML."""

    min_notional_1m_usd: float = Field(default=50000.0, gt=0)
    max_spread_bps: float = Field(default=10.0, gt=0)
    max_depth_imbalance: float = Field(default=0.7, ge=0.5, le=1.0)


class TimeWindowConfigYAML(BaseModel):
    """Time window configuration from YAML."""

    enabled: bool = False
    start_utc_hour: int = Field(default=12, ge=0, le=23)
    end_utc_hour: int = Field(default=22, ge=0, le=23)
    restrict_symbols: List[str] = Field(default_factory=list)


class MicrostructureConfigYAML(BaseModel):
    """Microstructure configuration schema matching YAML structure."""

    # Default thresholds
    default_min_notional_1m_usd: float = Field(default=50000.0, gt=0)
    default_max_spread_bps: float = Field(default=10.0, gt=0)
    default_max_depth_imbalance: float = Field(default=0.7, ge=0.5, le=1.0)
    notional_window_seconds: int = Field(default=60, gt=0)

    # Pair-specific overrides
    pair_configs: Dict[str, PairConfigYAML] = Field(default_factory=dict)

    # Time window
    time_window: TimeWindowConfigYAML = Field(default_factory=TimeWindowConfigYAML)


def load_microstructure_config_from_yaml(yaml_path: str | Path) -> MicrostructureConfigYAML:
    """
    Load microstructure configuration from YAML file.

    Args:
        yaml_path: Path to YAML configuration file

    Returns:
        Validated MicrostructureConfigYAML

    Raises:
        FileNotFoundError: If YAML file not found
        ValidationError: If configuration invalid
    """
    yaml_path = Path(yaml_path)

    if not yaml_path.exists():
        raise FileNotFoundError(f"Microstructure config file not found: {yaml_path}")

    logger.info(f"Loading microstructure configuration from {yaml_path}")

    with open(yaml_path, "r") as f:
        config_dict = yaml.safe_load(f)

    if "microstructure" not in config_dict:
        logger.warning(f"Missing 'microstructure' section in {yaml_path}, using defaults")
        return MicrostructureConfigYAML()

    microstructure_section = config_dict["microstructure"]

    try:
        config = MicrostructureConfigYAML(**microstructure_section)
        logger.info(
            f"Loaded microstructure config: default_notional={config.default_min_notional_1m_usd}, "
            f"default_spread={config.default_max_spread_bps}bps, "
            f"pair_configs={len(config.pair_configs)}"
        )
        return config
    except ValidationError as e:
        logger.error(f"Invalid microstructure configuration: {e}")
        raise


def yaml_to_microstructure_config(config: MicrostructureConfigYAML) -> MicrostructureConfig:
    """
    Convert YAML config to MicrostructureConfig.

    Args:
        config: Microstructure configuration from YAML

    Returns:
        MicrostructureConfig instance ready for MicrostructureGate
    """
    # Convert pair configs
    pair_configs = {}
    for symbol, pair_yaml in config.pair_configs.items():
        pair_configs[symbol] = PairLiquidityConfig(
            symbol=symbol,
            min_notional_1m_usd=pair_yaml.min_notional_1m_usd,
            max_spread_bps=pair_yaml.max_spread_bps,
            max_depth_imbalance=pair_yaml.max_depth_imbalance,
        )

    # Convert time window
    time_window = TimeWindowConfig(
        enabled=config.time_window.enabled,
        start_utc_hour=config.time_window.start_utc_hour,
        end_utc_hour=config.time_window.end_utc_hour,
        restrict_symbols=config.time_window.restrict_symbols,
    )

    microstructure_config = MicrostructureConfig(
        pair_configs=pair_configs,
        default_min_notional_1m_usd=config.default_min_notional_1m_usd,
        default_max_spread_bps=config.default_max_spread_bps,
        default_max_depth_imbalance=config.default_max_depth_imbalance,
        time_window=time_window,
        notional_window_seconds=config.notional_window_seconds,
    )

    logger.info(
        f"Created MicrostructureConfig: window={config.notional_window_seconds}s, "
        f"pairs={len(pair_configs)}, time_window_enabled={time_window.enabled}"
    )

    return microstructure_config


def load_microstructure_gate_config(yaml_path: str | Path) -> MicrostructureConfig:
    """
    Load MicrostructureConfig directly from YAML file.

    Convenience function that combines load_microstructure_config_from_yaml
    and yaml_to_microstructure_config.

    Args:
        yaml_path: Path to YAML configuration file

    Returns:
        MicrostructureConfig ready for MicrostructureGate

    Example:
        >>> config = load_microstructure_gate_config("config/settings.yaml")
        >>> gate = MicrostructureGate(config)
    """
    yaml_config = load_microstructure_config_from_yaml(yaml_path)
    return yaml_to_microstructure_config(yaml_config)


# =============================================================================
# CLI OVERRIDE SUPPORT
# =============================================================================


def override_time_window(
    config: MicrostructureConfig,
    enabled: Optional[bool] = None,
    start_hour: Optional[int] = None,
    end_hour: Optional[int] = None,
) -> MicrostructureConfig:
    """
    Override time window settings via CLI flags.

    Args:
        config: Base configuration
        enabled: Override enabled flag
        start_hour: Override start UTC hour
        end_hour: Override end UTC hour

    Returns:
        Updated configuration

    Example:
        >>> config = load_microstructure_gate_config("config/settings.yaml")
        >>> # CLI: --trade_window 14-20
        >>> config = override_time_window(config, enabled=True, start_hour=14, end_hour=20)
    """
    if enabled is not None:
        config.time_window.enabled = enabled

    if start_hour is not None:
        if not 0 <= start_hour <= 23:
            raise ValueError(f"start_hour must be in [0, 23], got {start_hour}")
        config.time_window.start_utc_hour = start_hour

    if end_hour is not None:
        if not 0 <= end_hour <= 23:
            raise ValueError(f"end_hour must be in [0, 23], got {end_hour}")
        config.time_window.end_utc_hour = end_hour

    logger.info(
        f"Time window overridden: enabled={config.time_window.enabled}, "
        f"window={config.time_window.start_utc_hour:02d}:00-{config.time_window.end_utc_hour:02d}:00 UTC"
    )

    return config


def parse_trade_window_arg(arg: str) -> tuple[int, int]:
    """
    Parse --trade_window CLI argument.

    Args:
        arg: CLI argument in format "START-END" (e.g., "12-22", "14-20")

    Returns:
        (start_hour, end_hour) tuple

    Raises:
        ValueError: If format invalid

    Example:
        >>> start, end = parse_trade_window_arg("12-22")
        >>> # start=12, end=22
    """
    try:
        parts = arg.split("-")
        if len(parts) != 2:
            raise ValueError("Expected format: START-END (e.g., '12-22')")

        start_hour = int(parts[0])
        end_hour = int(parts[1])

        if not 0 <= start_hour <= 23:
            raise ValueError(f"start_hour must be in [0, 23], got {start_hour}")
        if not 0 <= end_hour <= 23:
            raise ValueError(f"end_hour must be in [0, 23], got {end_hour}")

        return start_hour, end_hour
    except Exception as e:
        raise ValueError(f"Invalid --trade_window format '{arg}': {e}")


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test config loading"""
    import sys

    logging.basicConfig(level=logging.INFO)

    try:
        # Test 1: Load from settings.yaml
        config_path = Path(__file__).parent / "settings.yaml"

        if not config_path.exists():
            print(f"WARNING: Config file not found at {config_path}, creating minimal test config")
            # Create minimal test config
            test_config = {
                "microstructure": {
                    "default_min_notional_1m_usd": 50000.0,
                    "default_max_spread_bps": 10.0,
                    "default_max_depth_imbalance": 0.7,
                    "notional_window_seconds": 60,
                    "pair_configs": {
                        "BTC/USD": {
                            "min_notional_1m_usd": 100000.0,
                            "max_spread_bps": 5.0,
                            "max_depth_imbalance": 0.65,
                        }
                    },
                    "time_window": {
                        "enabled": False,
                        "start_utc_hour": 12,
                        "end_utc_hour": 22,
                        "restrict_symbols": ["*USD"],
                    },
                }
            }
            with open("test_microstructure_config.yaml", "w") as f:
                yaml.dump(test_config, f)
            config_path = Path("test_microstructure_config.yaml")

        print(f"\nTest 1: Loading microstructure config from {config_path}")
        yaml_config = load_microstructure_config_from_yaml(config_path)
        print(f"  [+] Loaded: default_notional={yaml_config.default_min_notional_1m_usd}")
        print(f"  [+] Pair configs: {len(yaml_config.pair_configs)}")

        # Test 2: Convert to MicrostructureConfig
        print("\nTest 2: Converting to MicrostructureConfig")
        config = yaml_to_microstructure_config(yaml_config)
        print(f"  [+] default_min_notional_1m_usd={config.default_min_notional_1m_usd}")
        print(f"  [+] pair_configs={len(config.pair_configs)}")
        print(f"  [+] time_window.enabled={config.time_window.enabled}")

        # Test 3: Direct load
        print("\nTest 3: Direct load (convenience function)")
        config2 = load_microstructure_gate_config(config_path)
        assert config2.default_min_notional_1m_usd == config.default_min_notional_1m_usd
        print(f"  [+] Direct load successful")

        # Test 4: CLI override
        print("\nTest 4: CLI time window override")
        start, end = parse_trade_window_arg("14-20")
        assert start == 14 and end == 20
        print(f"  [+] Parsed --trade_window 14-20: start={start}, end={end}")

        config3 = override_time_window(config2, enabled=True, start_hour=14, end_hour=20)
        assert config3.time_window.enabled == True
        assert config3.time_window.start_utc_hour == 14
        assert config3.time_window.end_utc_hour == 20
        print(f"  [+] Time window overridden: {config3.time_window.start_utc_hour:02d}:00-{config3.time_window.end_utc_hour:02d}:00 UTC")

        # Test 5: Get pair config
        print("\nTest 5: Get pair config (with fallback)")
        btc_config = config.get_pair_config("BTC/USD")
        print(f"  [+] BTC/USD: notional={btc_config.min_notional_1m_usd}")

        unknown_config = config.get_pair_config("XYZ/USD")
        assert unknown_config.min_notional_1m_usd == config.default_min_notional_1m_usd
        print(f"  [+] XYZ/USD (fallback): notional={unknown_config.min_notional_1m_usd}")

        print("\n[PASS] Microstructure Config Loader Self-Check")

        # Cleanup test file if created
        if config_path.name == "test_microstructure_config.yaml":
            config_path.unlink()

    except Exception as e:
        print(f"\n[FAIL] Microstructure Config Loader Self-Check: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
