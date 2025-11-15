"""
tuning - Automated Parameter Optimization

Production-grade parameter tuning with grid/Bayesian sweeps.

Per PRD §10:
- Maximize PF subject to DD ≤ 20% and monthly ROI ≥ 10%
- Search MA lengths, BB width, RR min, SL multipliers, confidence threshold
- Save top-k param sets
- Generate sweep summary report

Exports:
- ParameterSweep: Main sweep engine
- SweepConfig: Configuration
- Objective: Objective function with constraints
- run_sweep: Convenience function

Example:
    >>> from tuning import ParameterSweep, SweepConfig
    >>> config = SweepConfig(
    ...     pairs=["BTC/USD"],
    ...     lookback_days=720,
    ...     max_dd_threshold=20.0,
    ...     min_monthly_roi=10.0,
    ... )
    >>> sweep = ParameterSweep(config=config)
    >>> results = sweep.run(method="grid", top_k=5)
    >>> sweep.save_top_params("config/params/top")

Author: Crypto AI Bot Team
"""

from tuning.sweep import ParameterSweep, SweepConfig, run_sweep
from tuning.objectives import Objective, evaluate_config

__all__ = [
    "ParameterSweep",
    "SweepConfig",
    "Objective",
    "run_sweep",
    "evaluate_config",
]
