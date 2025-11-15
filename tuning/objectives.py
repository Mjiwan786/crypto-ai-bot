#!/usr/bin/env python3
"""
tuning/objectives.py - Objective Functions for Parameter Optimization

KPI constraint validation and objective scoring for parameter sweeps.

Per PRD §10:
- Maximize PF subject to DD ≤ 20% and monthly ROI ≥ 10%
- Multi-objective optimization with constraints
- Pareto-optimal ranking when multiple objectives

Features:
- Objective function with hard constraints (DD, ROI)
- Multi-objective scoring (PF primary, Sharpe secondary)
- Constraint violation tracking
- Pareto frontier analysis

Example:
    >>> from tuning import Objective, evaluate_config
    >>> objective = Objective(max_dd=20.0, min_monthly_roi=10.0)
    >>> score, violations = objective.evaluate(metrics)
    >>> if not violations:
    ...     print(f"Config meets constraints with PF={metrics.profit_factor}")

Author: Crypto AI Bot Team
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from backtests.metrics import BacktestMetrics

logger = logging.getLogger(__name__)


# =============================================================================
# OBJECTIVE CONFIGURATION
# =============================================================================

@dataclass
class ObjectiveConfig:
    """
    Configuration for objective function.

    Attributes:
        max_dd: Maximum drawdown threshold (%)
        min_monthly_roi: Minimum monthly ROI threshold (%)
        primary_metric: Primary optimization metric ("profit_factor", "sharpe", "roi")
        secondary_metric: Secondary metric for tie-breaking
        require_min_trades: Minimum number of trades required
        weight_primary: Weight for primary metric (0-1)
        weight_secondary: Weight for secondary metric (0-1)
    """
    max_dd: float = 20.0
    min_monthly_roi: float = 10.0
    primary_metric: str = "profit_factor"
    secondary_metric: str = "sharpe_ratio"
    require_min_trades: int = 10
    weight_primary: float = 0.8
    weight_secondary: float = 0.2

    def __post_init__(self):
        """Validate configuration"""
        if self.weight_primary + self.weight_secondary != 1.0:
            raise ValueError("Weights must sum to 1.0")

        if self.primary_metric not in ["profit_factor", "sharpe_ratio", "monthly_roi_mean"]:
            raise ValueError(f"Invalid primary metric: {self.primary_metric}")


# =============================================================================
# OBJECTIVE FUNCTION
# =============================================================================

class Objective:
    """
    Objective function for parameter optimization.

    Evaluates backtest metrics against KPI constraints and computes objective score.
    """

    def __init__(self, config: Optional[ObjectiveConfig] = None):
        """
        Initialize objective function.

        Args:
            config: Objective configuration (uses defaults if None)
        """
        self.config = config or ObjectiveConfig()

        logger.info(f"Objective initialized: max_dd={self.config.max_dd}%, "
                   f"min_roi={self.config.min_monthly_roi}%, "
                   f"primary={self.config.primary_metric}")

    def evaluate(self, metrics: BacktestMetrics) -> Tuple[float, List[str]]:
        """
        Evaluate metrics against objective function.

        Args:
            metrics: Backtest metrics

        Returns:
            Tuple of (score, constraint_violations)
            - score: Objective score (higher is better, -inf if constraints violated)
            - constraint_violations: List of constraint violation descriptions
        """
        violations = []

        # Check hard constraints
        if float(metrics.max_drawdown) > self.config.max_dd:
            violations.append(
                f"Max DD {metrics.max_drawdown:.2f}% exceeds threshold {self.config.max_dd}%"
            )

        if float(metrics.monthly_roi_mean) < self.config.min_monthly_roi:
            violations.append(
                f"Monthly ROI {metrics.monthly_roi_mean:.2f}% below threshold {self.config.min_monthly_roi}%"
            )

        if metrics.total_trades < self.config.require_min_trades:
            violations.append(
                f"Total trades {metrics.total_trades} below minimum {self.config.require_min_trades}"
            )

        # If constraints violated, return heavily penalized score
        if violations:
            penalty = -1000.0 - len(violations) * 100.0
            return penalty, violations

        # Compute objective score (weighted combination)
        primary_value = self._get_metric_value(metrics, self.config.primary_metric)
        secondary_value = self._get_metric_value(metrics, self.config.secondary_metric)

        # Normalize metrics to [0, 1] scale for combining
        # Use sigmoid-like normalization
        primary_norm = self._normalize_metric(primary_value, self.config.primary_metric)
        secondary_norm = self._normalize_metric(secondary_value, self.config.secondary_metric)

        score = (
            self.config.weight_primary * primary_norm +
            self.config.weight_secondary * secondary_norm
        )

        return score, violations

    def _get_metric_value(self, metrics: BacktestMetrics, metric_name: str) -> float:
        """
        Extract metric value from backtest metrics.

        Args:
            metrics: Backtest metrics
            metric_name: Name of metric to extract

        Returns:
            Metric value as float
        """
        metric_map = {
            "profit_factor": metrics.profit_factor,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
            "calmar_ratio": metrics.calmar_ratio,
            "monthly_roi_mean": metrics.monthly_roi_mean,
            "total_return_pct": metrics.total_return_pct,
            "win_rate": metrics.win_rate,
        }

        if metric_name not in metric_map:
            raise ValueError(f"Unknown metric: {metric_name}")

        return float(metric_map[metric_name])

    def _normalize_metric(self, value: float, metric_name: str) -> float:
        """
        Normalize metric value to [0, 1] scale.

        Uses sigmoid-like transformation centered around typical good values.

        Args:
            value: Raw metric value
            metric_name: Metric name

        Returns:
            Normalized value in [0, 1]
        """
        # Define typical "good" values and scales for each metric
        normalization_params = {
            "profit_factor": {"center": 2.5, "scale": 1.0},
            "sharpe_ratio": {"center": 1.5, "scale": 0.5},
            "sortino_ratio": {"center": 2.0, "scale": 0.5},
            "calmar_ratio": {"center": 1.0, "scale": 0.5},
            "monthly_roi_mean": {"center": 15.0, "scale": 5.0},
            "total_return_pct": {"center": 100.0, "scale": 50.0},
            "win_rate": {"center": 60.0, "scale": 10.0},
        }

        if metric_name not in normalization_params:
            # Default normalization
            return min(1.0, max(0.0, value / 10.0))

        params = normalization_params[metric_name]
        center = params["center"]
        scale = params["scale"]

        # Sigmoid transformation: 1 / (1 + exp(-(x - center) / scale))
        import math
        normalized = 1.0 / (1.0 + math.exp(-(value - center) / scale))

        return normalized

    def rank_results(self, results: List[Dict]) -> List[Dict]:
        """
        Rank results by objective score.

        Args:
            results: List of result dictionaries with "metrics" key

        Returns:
            Sorted list of results (best first)
        """
        scored_results = []

        for result in results:
            metrics = result["metrics"]
            score, violations = self.evaluate(metrics)

            result["objective_score"] = score
            result["constraint_violations"] = violations
            result["meets_constraints"] = len(violations) == 0

            scored_results.append(result)

        # Sort by score (descending)
        scored_results.sort(key=lambda r: r["objective_score"], reverse=True)

        return scored_results


# =============================================================================
# PARETO FRONTIER ANALYSIS
# =============================================================================

def compute_pareto_frontier(
    results: List[Dict],
    objectives: List[str],
) -> List[Dict]:
    """
    Compute Pareto frontier for multi-objective optimization.

    A solution is Pareto-optimal if no other solution is better in all objectives.

    Args:
        results: List of result dictionaries
        objectives: List of objective metric names (e.g., ["profit_factor", "sharpe_ratio"])

    Returns:
        List of Pareto-optimal results
    """
    pareto_optimal = []

    for i, result_i in enumerate(results):
        is_dominated = False

        for j, result_j in enumerate(results):
            if i == j:
                continue

            # Check if result_j dominates result_i
            # (better in all objectives, strictly better in at least one)
            dominates = True
            strictly_better_in_one = False

            for obj in objectives:
                val_i = result_i["metrics"].get(obj, 0.0)
                val_j = result_j["metrics"].get(obj, 0.0)

                if val_j < val_i:
                    dominates = False
                    break

                if val_j > val_i:
                    strictly_better_in_one = True

            if dominates and strictly_better_in_one:
                is_dominated = True
                break

        if not is_dominated:
            pareto_optimal.append(result_i)

    logger.info(f"Found {len(pareto_optimal)} Pareto-optimal solutions out of {len(results)}")

    return pareto_optimal


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def evaluate_config(
    metrics: BacktestMetrics,
    max_dd: float = 20.0,
    min_monthly_roi: float = 10.0,
) -> Tuple[bool, List[str]]:
    """
    Convenience function to check if config meets KPI constraints.

    Args:
        metrics: Backtest metrics
        max_dd: Maximum drawdown threshold (%)
        min_monthly_roi: Minimum monthly ROI threshold (%)

    Returns:
        Tuple of (meets_constraints, violations)
    """
    objective = Objective(config=ObjectiveConfig(
        max_dd=max_dd,
        min_monthly_roi=min_monthly_roi,
    ))

    score, violations = objective.evaluate(metrics)

    return len(violations) == 0, violations


def select_best_config(
    results: List[Dict],
    max_dd: float = 20.0,
    min_monthly_roi: float = 10.0,
    primary_metric: str = "profit_factor",
) -> Optional[Dict]:
    """
    Select best configuration from sweep results.

    Args:
        results: List of sweep results
        max_dd: Maximum drawdown threshold
        min_monthly_roi: Minimum monthly ROI threshold
        primary_metric: Primary optimization metric

    Returns:
        Best result dictionary, or None if no config meets constraints
    """
    objective = Objective(config=ObjectiveConfig(
        max_dd=max_dd,
        min_monthly_roi=min_monthly_roi,
        primary_metric=primary_metric,
    ))

    ranked = objective.rank_results(results)

    # Return best result that meets constraints
    for result in ranked:
        if result["meets_constraints"]:
            return result

    logger.warning("No configuration meets KPI constraints")
    return None


def check_constraint_satisfaction(
    metrics: BacktestMetrics,
    max_dd: float = 20.0,
    min_monthly_roi: float = 10.0,
    min_trades: int = 10,
) -> Dict[str, bool]:
    """
    Check individual constraint satisfaction.

    Args:
        metrics: Backtest metrics
        max_dd: Maximum drawdown threshold (%)
        min_monthly_roi: Minimum monthly ROI threshold (%)
        min_trades: Minimum number of trades

    Returns:
        Dictionary mapping constraint name to satisfaction status
    """
    return {
        "max_drawdown": float(metrics.max_drawdown) <= max_dd,
        "monthly_roi": float(metrics.monthly_roi_mean) >= min_monthly_roi,
        "min_trades": metrics.total_trades >= min_trades,
        "profit_factor_positive": float(metrics.profit_factor) > 1.0,
        "positive_expectancy": float(metrics.expectancy) > 0.0,
    }
