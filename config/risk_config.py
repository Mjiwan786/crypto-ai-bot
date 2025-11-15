"""
Risk configuration loader for drawdown protection.

Loads risk gates configuration from YAML and converts to DrawdownBands.
Validates configuration and provides defaults.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml
from pydantic import BaseModel, Field, ValidationError

# Import DrawdownBands directly to avoid circular imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.risk.drawdown_protector import DrawdownBands

logger = logging.getLogger(__name__)


class RiskConfig(BaseModel):
    """Risk configuration schema matching YAML structure."""

    # Position sizing
    max_position_pct: float = Field(default=0.05, gt=0, le=1.0)
    stop_loss_pct: float = Field(default=0.02, gt=0, le=1.0)
    take_profit_pct: float = Field(default=0.04, gt=0, le=1.0)
    max_concurrent_positions: int = Field(default=3, gt=0)
    position_sizing_method: str = "fixed_percentage"
    risk_per_trade_pct: float = Field(default=0.8, gt=0, le=100.0)

    # Drawdown gates
    day_max_drawdown_pct: float = Field(default=4.0, gt=0, le=100.0)
    rolling_max_drawdown_pct: float = Field(default=12.0, gt=0, le=100.0)
    max_consecutive_losses: int = Field(default=3, gt=0, le=100)
    cooldown_after_losses_s: int = Field(default=3600, ge=0)

    # Risk scaling bands
    scale_bands: List[Dict[str, float]] = Field(default_factory=list)

    # Rolling windows
    rolling_windows: List[Dict[str, float]] = Field(default_factory=list)

    # Cooldowns
    cooldown_after_soft_s: int = Field(default=600, ge=0)
    cooldown_after_hard_s: int = Field(default=1800, ge=0)

    # Scope controls
    enable_per_strategy: bool = True
    enable_per_symbol: bool = True


def load_risk_config_from_yaml(yaml_path: str | Path) -> RiskConfig:
    """
    Load risk configuration from YAML file.

    Args:
        yaml_path: Path to YAML configuration file

    Returns:
        Validated RiskConfig

    Raises:
        FileNotFoundError: If YAML file not found
        ValidationError: If configuration invalid
    """
    yaml_path = Path(yaml_path)

    if not yaml_path.exists():
        raise FileNotFoundError(f"Risk config file not found: {yaml_path}")

    logger.info(f"Loading risk configuration from {yaml_path}")

    with open(yaml_path, "r") as f:
        config_dict = yaml.safe_load(f)

    if "risk" not in config_dict:
        raise ValueError(f"Missing 'risk' section in {yaml_path}")

    risk_section = config_dict["risk"]

    try:
        config = RiskConfig(**risk_section)
        logger.info(
            f"Loaded risk config: day_max_dd={config.day_max_drawdown_pct}%, "
            f"rolling_max_dd={config.rolling_max_drawdown_pct}%, "
            f"max_losses={config.max_consecutive_losses}"
        )
        return config
    except ValidationError as e:
        logger.error(f"Invalid risk configuration: {e}")
        raise


def risk_config_to_drawdown_bands(config: RiskConfig) -> DrawdownBands:
    """
    Convert RiskConfig to DrawdownBands for drawdown protector.

    Args:
        config: Risk configuration from YAML

    Returns:
        DrawdownBands instance ready for DrawdownProtector
    """
    # Convert percentage values to decimal fractions
    # YAML uses whole numbers (4.0 = 4%), code uses fractions (-0.04 = -4%)
    daily_stop_pct = -abs(config.day_max_drawdown_pct / 100.0)

    # Convert scale bands from YAML format to tuple format
    scale_bands: List[Tuple[float, float]] = []
    if config.scale_bands:
        for band in config.scale_bands:
            threshold_pct = band["threshold_pct"] / 100.0  # -1.0 -> -0.01
            multiplier = band["multiplier"]
            scale_bands.append((threshold_pct, multiplier))

    # Default scale bands if none provided
    if not scale_bands:
        scale_bands = [(-0.01, 0.75), (-0.02, 0.5), (-0.03, 0.25)]

    # Convert rolling windows from YAML format to tuple format
    rolling_windows: List[Tuple[int, float]] = []
    if config.rolling_windows:
        for window in config.rolling_windows:
            window_s = int(window["window_s"])
            limit_pct = window["limit_pct"] / 100.0  # -1.0 -> -0.01
            rolling_windows.append((window_s, limit_pct))

    # Default rolling windows if none provided (1h, 4h windows)
    if not rolling_windows:
        rolling_windows = [(3600, -0.01), (14400, -0.015)]

    bands = DrawdownBands(
        daily_stop_pct=daily_stop_pct,
        rolling_windows_pct=rolling_windows,
        max_consecutive_losses=config.max_consecutive_losses,
        cooldown_after_soft_s=config.cooldown_after_soft_s,
        cooldown_after_hard_s=config.cooldown_after_hard_s,
        scale_bands=scale_bands,
        enable_per_strategy=config.enable_per_strategy,
        enable_per_symbol=config.enable_per_symbol,
    )

    logger.info(
        f"Created DrawdownBands: daily_stop={daily_stop_pct:.2%}, "
        f"loss_streak={config.max_consecutive_losses}, "
        f"windows={len(rolling_windows)}, bands={len(scale_bands)}"
    )

    return bands


def load_drawdown_bands_from_yaml(yaml_path: str | Path) -> DrawdownBands:
    """
    Load DrawdownBands directly from YAML file.

    Convenience function that combines load_risk_config_from_yaml
    and risk_config_to_drawdown_bands.

    Args:
        yaml_path: Path to YAML configuration file

    Returns:
        DrawdownBands ready for DrawdownProtector

    Example:
        >>> bands = load_drawdown_bands_from_yaml("config/settings.yaml")
        >>> protector = DrawdownProtector(bands)
    """
    config = load_risk_config_from_yaml(yaml_path)
    return risk_config_to_drawdown_bands(config)


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Self-check: Test config loading"""
    import sys

    logging.basicConfig(level=logging.INFO)

    try:
        # Test 1: Load from example config
        config_path = Path(__file__).parent / "settings.yaml"

        if not config_path.exists():
            print(f"WARNING: Config file not found at {config_path}, creating minimal test config")
            # Create minimal test config
            test_config = {
                "risk": {
                    "day_max_drawdown_pct": 4.0,
                    "rolling_max_drawdown_pct": 12.0,
                    "max_consecutive_losses": 3,
                    "cooldown_after_losses_s": 3600,
                    "scale_bands": [
                        {"threshold_pct": -1.0, "multiplier": 0.75},
                        {"threshold_pct": -2.0, "multiplier": 0.50},
                    ],
                    "rolling_windows": [
                        {"window_s": 3600, "limit_pct": -1.0},
                        {"window_s": 14400, "limit_pct": -1.5},
                    ],
                    "cooldown_after_soft_s": 600,
                    "cooldown_after_hard_s": 1800,
                }
            }
            with open("test_risk_config.yaml", "w") as f:
                yaml.dump(test_config, f)
            config_path = Path("test_risk_config.yaml")

        print(f"\nTest 1: Loading risk config from {config_path}")
        config = load_risk_config_from_yaml(config_path)
        print(f"  [+] Loaded: day_dd={config.day_max_drawdown_pct}%, max_losses={config.max_consecutive_losses}")

        # Test 2: Convert to DrawdownBands
        print("\nTest 2: Converting to DrawdownBands")
        bands = risk_config_to_drawdown_bands(config)
        print(f"  [+] daily_stop_pct={bands.daily_stop_pct:.2%}")
        print(f"  [+] max_consecutive_losses={bands.max_consecutive_losses}")
        print(f"  [+] scale_bands={len(bands.scale_bands)} bands")
        print(f"  [+] rolling_windows={len(bands.rolling_windows_pct)} windows")

        # Test 3: Direct load
        print("\nTest 3: Direct load (convenience function)")
        bands2 = load_drawdown_bands_from_yaml(config_path)
        assert bands2.daily_stop_pct == bands.daily_stop_pct
        assert bands2.max_consecutive_losses == bands.max_consecutive_losses
        print(f"  [+] Direct load successful")

        # Test 4: Validate percentage conversion
        print("\nTest 4: Validate percentage conversion")
        assert bands.daily_stop_pct == -0.04, f"Expected -0.04, got {bands.daily_stop_pct}"
        assert bands.scale_bands[0][0] == -0.01, f"Expected -0.01, got {bands.scale_bands[0][0]}"
        print(f"  [+] Percentage conversion correct (YAML 4.0% -> -0.04)")

        print("\n[PASS] Risk Config Loader Self-Check")

        # Cleanup test file if created
        if config_path.name == "test_risk_config.yaml":
            config_path.unlink()

    except Exception as e:
        print(f"\n[FAIL] Risk Config Loader Self-Check: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
