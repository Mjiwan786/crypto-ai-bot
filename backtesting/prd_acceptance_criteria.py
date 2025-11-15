"""
PRD-001 Section 6.3 Acceptance Criteria Enforcer

This module implements PRD-001 Section 6.3 acceptance criteria with:
- Enforce Sharpe ratio ≥ 1.5 for production deployment
- Enforce max drawdown ≤ -15% (i.e., max drawdown must be better than -15%)
- Enforce win rate ≥ 45%
- Enforce profit factor ≥ 1.3
- Enforce minimum 200 trades in backtest period
- Block deployment if backtest fails acceptance criteria

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from backtesting.prd_metrics_calculator import BacktestMetrics

logger = logging.getLogger(__name__)

# PRD-001 Section 6.3: Acceptance criteria thresholds
MIN_SHARPE_RATIO = 1.5
MAX_DRAWDOWN_THRESHOLD = -15.0  # Max drawdown must be better than (less negative than) -15%
MIN_WIN_RATE = 45.0
MIN_PROFIT_FACTOR = 1.3
MIN_TRADES = 200


@dataclass
class AcceptanceCriteriaResult:
    """
    Result of acceptance criteria check.

    Attributes:
        passed: True if all criteria passed, False otherwise
        failures: List of failure messages
        metrics: Dictionary with criterion -> passed/failed
    """
    passed: bool
    failures: List[str]
    metrics: Dict[str, bool]

    def __repr__(self) -> str:
        """String representation."""
        status = "PASSED" if self.passed else "FAILED"
        return f"AcceptanceCriteriaResult({status}, {len(self.failures)} failures)"


class PRDAcceptanceCriteria:
    """
    PRD-001 Section 6.3 compliant acceptance criteria enforcer.

    Features:
    - Check all PRD-required acceptance criteria
    - Block deployment if criteria not met
    - Provide detailed failure reasons

    Usage:
        criteria = PRDAcceptanceCriteria()

        result = criteria.check_acceptance(metrics)

        if not result.passed:
            print("Backtest FAILED acceptance criteria:")
            for failure in result.failures:
                print(f"  - {failure}")
            # Block deployment
        else:
            print("Backtest PASSED - ready for production")
    """

    def __init__(
        self,
        min_sharpe_ratio: float = MIN_SHARPE_RATIO,
        max_drawdown_threshold: float = MAX_DRAWDOWN_THRESHOLD,
        min_win_rate: float = MIN_WIN_RATE,
        min_profit_factor: float = MIN_PROFIT_FACTOR,
        min_trades: int = MIN_TRADES
    ):
        """
        Initialize PRD-compliant acceptance criteria.

        Args:
            min_sharpe_ratio: Minimum Sharpe ratio (default 1.5)
            max_drawdown_threshold: Maximum allowed drawdown (default -15%)
            min_win_rate: Minimum win rate % (default 45%)
            min_profit_factor: Minimum profit factor (default 1.3)
            min_trades: Minimum number of trades (default 200)
        """
        # PRD-001 Section 6.3: Acceptance thresholds
        self.min_sharpe_ratio = min_sharpe_ratio
        self.max_drawdown_threshold = max_drawdown_threshold
        self.min_win_rate = min_win_rate
        self.min_profit_factor = min_profit_factor
        self.min_trades = min_trades

        logger.info(
            f"PRDAcceptanceCriteria initialized: "
            f"sharpe≥{min_sharpe_ratio}, "
            f"drawdown≤{max_drawdown_threshold}%, "
            f"win_rate≥{min_win_rate}%, "
            f"profit_factor≥{min_profit_factor}, "
            f"min_trades≥{min_trades}"
        )

    def check_acceptance(
        self,
        metrics: BacktestMetrics
    ) -> AcceptanceCriteriaResult:
        """
        PRD-001 Section 6.3: Check if backtest meets acceptance criteria.

        Checks all 5 criteria:
        1. Sharpe ratio ≥ 1.5
        2. Max drawdown ≤ -15% (better than -15%)
        3. Win rate ≥ 45%
        4. Profit factor ≥ 1.3
        5. Total trades ≥ 200

        Args:
            metrics: BacktestMetrics to check

        Returns:
            AcceptanceCriteriaResult with pass/fail and detailed failures
        """
        failures = []
        criteria_results = {}

        # PRD-001 Section 6.3 Item 1: Check Sharpe ratio ≥ 1.5
        sharpe_passed = metrics.sharpe_ratio >= self.min_sharpe_ratio
        criteria_results["sharpe_ratio"] = sharpe_passed
        if not sharpe_passed:
            failures.append(
                f"Sharpe ratio {metrics.sharpe_ratio:.2f} < {self.min_sharpe_ratio} (FAIL)"
            )

        # PRD-001 Section 6.3 Item 2: Check max drawdown ≤ -15%
        # Note: drawdown is negative, so -10% is better than -15%
        drawdown_passed = metrics.max_drawdown_pct >= self.max_drawdown_threshold
        criteria_results["max_drawdown"] = drawdown_passed
        if not drawdown_passed:
            failures.append(
                f"Max drawdown {metrics.max_drawdown_pct:.2f}% worse than {self.max_drawdown_threshold}% (FAIL)"
            )

        # PRD-001 Section 6.3 Item 3: Check win rate ≥ 45%
        win_rate_passed = metrics.win_rate >= self.min_win_rate
        criteria_results["win_rate"] = win_rate_passed
        if not win_rate_passed:
            failures.append(
                f"Win rate {metrics.win_rate:.2f}% < {self.min_win_rate}% (FAIL)"
            )

        # PRD-001 Section 6.3 Item 4: Check profit factor ≥ 1.3
        profit_factor_passed = metrics.profit_factor >= self.min_profit_factor
        criteria_results["profit_factor"] = profit_factor_passed
        if not profit_factor_passed:
            failures.append(
                f"Profit factor {metrics.profit_factor:.2f} < {self.min_profit_factor} (FAIL)"
            )

        # PRD-001 Section 6.3 Item 5: Check minimum 200 trades
        trades_passed = metrics.total_trades >= self.min_trades
        criteria_results["min_trades"] = trades_passed
        if not trades_passed:
            failures.append(
                f"Total trades {metrics.total_trades} < {self.min_trades} (FAIL)"
            )

        # Overall result
        passed = len(failures) == 0

        if passed:
            logger.info(
                f"[ACCEPTANCE PASSED] All criteria met: "
                f"sharpe={metrics.sharpe_ratio:.2f}, "
                f"drawdown={metrics.max_drawdown_pct:.2f}%, "
                f"win_rate={metrics.win_rate:.2f}%, "
                f"profit_factor={metrics.profit_factor:.2f}, "
                f"trades={metrics.total_trades}"
            )
        else:
            logger.error(
                f"[ACCEPTANCE FAILED] {len(failures)} criteria failed"
            )
            for failure in failures:
                logger.error(f"  - {failure}")

        return AcceptanceCriteriaResult(
            passed=passed,
            failures=failures,
            metrics=criteria_results
        )

    def check_and_raise(self, metrics: BacktestMetrics) -> None:
        """
        PRD-001 Section 6.3 Item 6: Block deployment if criteria not met.

        Checks acceptance criteria and raises exception if failed.

        Args:
            metrics: BacktestMetrics to check

        Raises:
            AcceptanceCriteriaError: If acceptance criteria not met
        """
        result = self.check_acceptance(metrics)

        if not result.passed:
            error_msg = (
                f"Backtest FAILED acceptance criteria - deployment BLOCKED:\n"
                + "\n".join(f"  - {failure}" for failure in result.failures)
            )
            raise AcceptanceCriteriaError(error_msg)

    def get_criteria_summary(self) -> Dict[str, Any]:
        """
        Get summary of acceptance criteria thresholds.

        Returns:
            Dictionary with all thresholds
        """
        return {
            "min_sharpe_ratio": self.min_sharpe_ratio,
            "max_drawdown_threshold": self.max_drawdown_threshold,
            "min_win_rate": self.min_win_rate,
            "min_profit_factor": self.min_profit_factor,
            "min_trades": self.min_trades
        }


class AcceptanceCriteriaError(Exception):
    """
    Exception raised when acceptance criteria are not met.

    PRD-001 Section 6.3 Item 6: Block deployment if backtest fails.
    """
    pass


# Singleton instance
_criteria_instance: Optional[PRDAcceptanceCriteria] = None


def get_acceptance_criteria() -> PRDAcceptanceCriteria:
    """
    Get singleton PRDAcceptanceCriteria instance.

    Returns:
        PRDAcceptanceCriteria instance
    """
    global _criteria_instance

    if _criteria_instance is None:
        _criteria_instance = PRDAcceptanceCriteria()

    return _criteria_instance


# Export for convenience
__all__ = [
    "PRDAcceptanceCriteria",
    "AcceptanceCriteriaResult",
    "AcceptanceCriteriaError",
    "get_acceptance_criteria",
    "MIN_SHARPE_RATIO",
    "MAX_DRAWDOWN_THRESHOLD",
    "MIN_WIN_RATE",
    "MIN_PROFIT_FACTOR",
    "MIN_TRADES",
]
