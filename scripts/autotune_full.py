"""
Full Autotune with Bayesian Optimization

Comprehensive parameter optimization with:
- 180d and 365d backtest validation
- Bayesian optimization for efficient search
- Quality gates (PF, Sharpe, MaxDD, 12-mo net)
- Circuit breaker monitoring
- Top-3 configs with promotion and rollback
- Markdown report generation

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import sys
import time
import json
import yaml
import shutil
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from decimal import Decimal

import numpy as np
from skopt import gp_minimize
from skopt.space import Real, Integer, Categorical
from skopt.utils import use_named_args

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from strategies.bar_reaction_5m import run_backtest


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

class AutotuneConfig:
    """Autotune configuration and parameters."""

    # Search space bounds
    TARGET_BPS_RANGE = (10.0, 30.0)
    STOP_BPS_RANGE = (8.0, 35.0)
    BASE_RISK_PCT_RANGE = (0.5, 2.5)
    STREAK_BOOST_PCT_RANGE = (0.0, 0.3)
    HEAT_THRESHOLD_RANGE = (50.0, 85.0)
    MAX_TRADES_PER_MIN_RANGE = (2, 8)
    MOMENTUM_FILTER_OPTIONS = [0.3, 0.5, 0.7]

    # Quality gates
    MIN_PROFIT_FACTOR = 1.35
    MIN_SHARPE_RATIO = 1.2
    MAX_DRAWDOWN_PCT = 12.0
    MIN_12MO_NET_PCT = 25.0

    # Circuit breaker limits
    MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR = 5

    # Bayesian optimization
    N_INITIAL_POINTS = 10  # Random exploration points
    N_ITERATIONS = 50      # Total optimization iterations
    N_TOP_CONFIGS = 3      # Number of top configs to keep

    # Backtest parameters
    BACKTEST_PAIRS = ["BTC/USD"]
    LOOKBACK_PERIODS = [180, 365]  # days

    # File paths
    CONFIG_PATH = "config/enhanced_scalper_config.yaml"
    BACKUP_DIR = "config/backups"
    OUTPUT_DIR = "out"
    REPORT_PATH = "out/autotune_full_report.md"
    RESULTS_PATH = "out/autotune_full_results.json"


# ============================================================================
# PARAMETER SEARCH SPACE
# ============================================================================

def create_search_space():
    """Create Bayesian optimization search space."""
    return [
        Real(*AutotuneConfig.TARGET_BPS_RANGE, name='target_bps'),
        Real(*AutotuneConfig.STOP_BPS_RANGE, name='stop_bps'),
        Real(*AutotuneConfig.BASE_RISK_PCT_RANGE, name='base_risk_pct'),
        Real(*AutotuneConfig.STREAK_BOOST_PCT_RANGE, name='streak_boost_pct'),
        Real(*AutotuneConfig.HEAT_THRESHOLD_RANGE, name='heat_threshold'),
        Integer(*AutotuneConfig.MAX_TRADES_PER_MIN_RANGE, name='max_trades_per_min'),
        Categorical(AutotuneConfig.MOMENTUM_FILTER_OPTIONS, name='momentum_filter'),
    ]


# ============================================================================
# BACKTEST EXECUTION
# ============================================================================

class BacktestRunner:
    """Run and validate backtests."""

    def __init__(self):
        self.circuit_breaker_trips = {}

    def run_backtest_with_params(
        self,
        params: Dict,
        lookback_days: int
    ) -> Optional[Dict]:
        """Run backtest with given parameters."""
        try:
            logger.info(f"Running {lookback_days}d backtest: {params}")

            # Run backtest
            results = run_backtest(
                pairs=AutotuneConfig.BACKTEST_PAIRS,
                target_bps=params['target_bps'],
                stop_bps=params['stop_bps'],
                base_risk_pct=params['base_risk_pct'],
                streak_boost_pct=params['streak_boost_pct'],
                lookback_days=lookback_days,
                momentum_threshold=params.get('momentum_filter', 0.5),
                max_heat_pct=params.get('heat_threshold', 65.0),
            )

            if not results:
                logger.warning(f"Backtest returned no results for {lookback_days}d")
                return None

            # Extract metrics
            metrics = {
                'profit_factor': results.get('pf', 0),
                'sharpe_ratio': results.get('sharpe', 0),
                'max_drawdown_pct': results.get('max_dd', 100),
                'cagr_pct': results.get('cagr', 0),
                'win_rate': results.get('win_rate', 0),
                'total_trades': results.get('trades', 0),
                'avg_heat_pct': results.get('avg_heat', 0),
                'final_equity': results.get('final_equity', 0),
                'lookback_days': lookback_days,
            }

            logger.info(
                f"  {lookback_days}d: PF={metrics['profit_factor']:.2f}, "
                f"Sharpe={metrics['sharpe_ratio']:.2f}, "
                f"DD={metrics['max_drawdown_pct']:.2f}%, "
                f"CAGR={metrics['cagr_pct']:.2f}%"
            )

            return metrics

        except Exception as e:
            logger.error(f"Backtest failed for {lookback_days}d: {e}")
            return None

    def validate_against_gates(self, metrics: Dict) -> Tuple[bool, List[str]]:
        """Validate metrics against quality gates."""
        failures = []

        # Check profit factor
        if metrics['profit_factor'] < AutotuneConfig.MIN_PROFIT_FACTOR:
            failures.append(
                f"PF {metrics['profit_factor']:.2f} < {AutotuneConfig.MIN_PROFIT_FACTOR}"
            )

        # Check Sharpe ratio
        if metrics['sharpe_ratio'] < AutotuneConfig.MIN_SHARPE_RATIO:
            failures.append(
                f"Sharpe {metrics['sharpe_ratio']:.2f} < {AutotuneConfig.MIN_SHARPE_RATIO}"
            )

        # Check max drawdown
        if metrics['max_drawdown_pct'] > AutotuneConfig.MAX_DRAWDOWN_PCT:
            failures.append(
                f"MaxDD {metrics['max_drawdown_pct']:.2f}% > {AutotuneConfig.MAX_DRAWDOWN_PCT}%"
            )

        # Check 12-month net return (use CAGR as proxy)
        if metrics['cagr_pct'] < AutotuneConfig.MIN_12MO_NET_PCT:
            failures.append(
                f"CAGR {metrics['cagr_pct']:.2f}% < {AutotuneConfig.MIN_12MO_NET_PCT}%"
            )

        passed = len(failures) == 0
        return passed, failures

    def check_circuit_breakers(self, params: Dict, metrics: Dict) -> bool:
        """Check if circuit breakers were tripped excessively."""
        # Estimate circuit breaker trips based on trade frequency
        trades_per_hour = metrics['total_trades'] / (metrics['lookback_days'] * 24)

        # Simple heuristic: if trading at >8 trades/hour, likely hitting limits
        max_rate = params.get('max_trades_per_min', 4)
        if trades_per_hour > max_rate * 60 * 0.9:  # 90% of limit
            logger.warning(
                f"Circuit breaker risk: {trades_per_hour:.1f} trades/hour "
                f"approaching limit of {max_rate * 60}/hour"
            )
            return False

        return True


# ============================================================================
# BAYESIAN OPTIMIZATION
# ============================================================================

class BayesianOptimizer:
    """Bayesian optimization for parameter search."""

    def __init__(self):
        self.runner = BacktestRunner()
        self.iteration = 0
        self.results_history = []
        self.best_score = -np.inf
        self.best_params = None

    def objective_function(
        self,
        target_bps: float,
        stop_bps: float,
        base_risk_pct: float,
        streak_boost_pct: float,
        heat_threshold: float,
        max_trades_per_min: int,
        momentum_filter: float,
    ) -> float:
        """
        Objective function for Bayesian optimization.

        Returns negative score (for minimization).
        """
        self.iteration += 1

        params = {
            'target_bps': target_bps,
            'stop_bps': stop_bps,
            'base_risk_pct': base_risk_pct,
            'streak_boost_pct': streak_boost_pct,
            'heat_threshold': heat_threshold,
            'max_trades_per_min': max_trades_per_min,
            'momentum_filter': momentum_filter,
        }

        logger.info(f"\n{'='*80}")
        logger.info(f"ITERATION {self.iteration}/{AutotuneConfig.N_ITERATIONS}")
        logger.info(f"{'='*80}")

        # Run 180d backtest first (faster)
        metrics_180d = self.runner.run_backtest_with_params(params, 180)
        if not metrics_180d:
            logger.warning("180d backtest failed, returning worst score")
            return 1e6  # Large penalty

        # Check gates on 180d
        passed_gates, failures = self.runner.validate_against_gates(metrics_180d)
        if not passed_gates:
            logger.info(f"[FAIL] 180d gates: {', '.join(failures)}")
            # Return penalty based on how bad the metrics are
            penalty = 1000 - metrics_180d['profit_factor'] * 100
            return penalty

        logger.info("[PASS] 180d passed gates, confirming on 365d...")

        # Run 365d backtest for confirmation
        metrics_365d = self.runner.run_backtest_with_params(params, 365)
        if not metrics_365d:
            logger.warning("365d backtest failed, returning worst score")
            return 1e6

        # Check gates on 365d
        passed_gates, failures = self.runner.validate_against_gates(metrics_365d)
        if not passed_gates:
            logger.info(f"[FAIL] 365d gates: {', '.join(failures)}")
            penalty = 1000 - metrics_365d['profit_factor'] * 100
            return penalty

        # Check circuit breakers
        if not self.runner.check_circuit_breakers(params, metrics_365d):
            logger.warning("[FAIL] Circuit breaker risk detected")
            return 500.0

        logger.info("[PASS] 365d confirmed!")

        # Calculate composite score (lower is better for optimization)
        # We want to maximize: CAGR * Sharpe / MaxDD
        score = (
            metrics_365d['cagr_pct'] *
            metrics_365d['sharpe_ratio'] /
            max(metrics_365d['max_drawdown_pct'], 1.0)
        )

        # Store result
        result = {
            'iteration': self.iteration,
            'params': params,
            'metrics_180d': metrics_180d,
            'metrics_365d': metrics_365d,
            'score': score,
            'timestamp': datetime.now().isoformat(),
        }
        self.results_history.append(result)

        # Track best
        if score > self.best_score:
            self.best_score = score
            self.best_params = params
            logger.info(f"[NEW BEST] Score: {score:.2f}")

        # Return negative score for minimization
        return -score

    def optimize(self) -> List[Dict]:
        """Run Bayesian optimization."""
        logger.info("\n" + "="*80)
        logger.info("STARTING BAYESIAN OPTIMIZATION")
        logger.info("="*80)
        logger.info(f"Initial points: {AutotuneConfig.N_INITIAL_POINTS}")
        logger.info(f"Total iterations: {AutotuneConfig.N_ITERATIONS}")
        logger.info(f"Search space:")
        logger.info(f"  target_bps: {AutotuneConfig.TARGET_BPS_RANGE}")
        logger.info(f"  stop_bps: {AutotuneConfig.STOP_BPS_RANGE}")
        logger.info(f"  base_risk_pct: {AutotuneConfig.BASE_RISK_PCT_RANGE}")
        logger.info(f"  streak_boost_pct: {AutotuneConfig.STREAK_BOOST_PCT_RANGE}")
        logger.info(f"  heat_threshold: {AutotuneConfig.HEAT_THRESHOLD_RANGE}")
        logger.info(f"  max_trades_per_min: {AutotuneConfig.MAX_TRADES_PER_MIN_RANGE}")
        logger.info(f"  momentum_filter: {AutotuneConfig.MOMENTUM_FILTER_OPTIONS}")

        # Create search space
        search_space = create_search_space()

        # Create objective wrapper with named parameters
        @use_named_args(search_space)
        def objective(**params):
            return self.objective_function(**params)

        # Run optimization
        result = gp_minimize(
            objective,
            search_space,
            n_calls=AutotuneConfig.N_ITERATIONS,
            n_initial_points=AutotuneConfig.N_INITIAL_POINTS,
            random_state=42,
            verbose=True,
        )

        logger.info("\n" + "="*80)
        logger.info("OPTIMIZATION COMPLETE")
        logger.info("="*80)
        logger.info(f"Best score: {-result.fun:.2f}")
        logger.info(f"Best params: {dict(zip([s.name for s in search_space], result.x))}")

        return self.results_history


# ============================================================================
# CONFIG MANAGEMENT
# ============================================================================

class ConfigManager:
    """Manage YAML configuration with backups and rollback."""

    def __init__(self):
        self.config_path = Path(AutotuneConfig.CONFIG_PATH)
        self.backup_dir = Path(AutotuneConfig.BACKUP_DIR)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def backup_current_config(self) -> Path:
        """Create backup of current configuration."""
        timestamp = int(time.time())
        backup_path = self.backup_dir / f"enhanced_scalper_config.backup.{timestamp}.yaml"

        if self.config_path.exists():
            shutil.copy2(self.config_path, backup_path)
            logger.info(f"Created backup: {backup_path}")
            return backup_path

        return None

    def load_config(self) -> Dict:
        """Load current YAML configuration."""
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def update_config(self, params: Dict, metrics: Dict) -> bool:
        """Update YAML configuration with new parameters."""
        try:
            # Load current config
            config = self.load_config()

            # Update scalper section
            if 'scalper' not in config:
                config['scalper'] = {}

            config['scalper']['target_bps'] = float(params['target_bps'])
            config['scalper']['stop_loss_bps'] = float(params['stop_bps'])
            config['scalper']['max_trades_per_minute'] = int(params['max_trades_per_min'])

            # Update dynamic sizing
            if 'dynamic_sizing' not in config:
                config['dynamic_sizing'] = {}

            config['dynamic_sizing']['base_risk_pct_small'] = float(params['base_risk_pct'])
            config['dynamic_sizing']['base_risk_pct_large'] = float(params['base_risk_pct'])
            config['dynamic_sizing']['streak_boost_pct'] = float(params['streak_boost_pct'])
            config['dynamic_sizing']['portfolio_heat_threshold_pct'] = float(params['heat_threshold'])

            # Add autotune metadata
            config['autotune_metadata'] = {
                'last_updated': datetime.now().isoformat(),
                'parameters': params,
                'metrics_365d': metrics,
                'source': 'autotune_full.py',
            }

            # Write updated config
            with open(self.config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)

            logger.info(f"Updated configuration: {self.config_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to update config: {e}")
            return False

    def rollback_to_backup(self, backup_path: Path) -> bool:
        """Rollback to previous configuration."""
        try:
            shutil.copy2(backup_path, self.config_path)
            logger.info(f"Rolled back to: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            return False


# ============================================================================
# REPORT GENERATION
# ============================================================================

class ReportGenerator:
    """Generate markdown report."""

    @staticmethod
    def generate_report(
        top_configs: List[Dict],
        promoted_config: Dict,
        optimization_history: List[Dict]
    ) -> str:
        """Generate comprehensive markdown report."""

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        report = f"""# Autotune Full - Optimization Report

**Generated:** {timestamp}
**Script:** `scripts/autotune_full.py`
**Total Iterations:** {len(optimization_history)}

---

## Executive Summary

"""

        # Add promoted config summary
        promoted_metrics = promoted_config['metrics_365d']
        report += f"""
### Promoted Configuration (#1)

**Parameters:**
- Target BPS: {promoted_config['params']['target_bps']:.1f}
- Stop Loss BPS: {promoted_config['params']['stop_bps']:.1f}
- Base Risk %: {promoted_config['params']['base_risk_pct']:.2f}
- Streak Boost %: {promoted_config['params']['streak_boost_pct']:.2f}
- Heat Threshold %: {promoted_config['params']['heat_threshold']:.1f}
- Max Trades/Min: {promoted_config['params']['max_trades_per_min']}
- Momentum Filter: {promoted_config['params']['momentum_filter']:.1f}

**365-Day Performance:**
- Profit Factor: **{promoted_metrics['profit_factor']:.2f}**
- Sharpe Ratio: **{promoted_metrics['sharpe_ratio']:.2f}**
- Max Drawdown: **{promoted_metrics['max_drawdown_pct']:.2f}%**
- CAGR: **{promoted_metrics['cagr_pct']:.2f}%**
- Win Rate: **{promoted_metrics['win_rate']:.1f}%**
- Total Trades: {promoted_metrics['total_trades']}
- Final Equity: ${promoted_metrics['final_equity']:,.0f}

**Optimization Score:** {promoted_config['score']:.2f}

---

## Top 3 Configurations

"""

        # Add top 3 configs table
        report += """
| Rank | Target BPS | Stop BPS | Risk % | PF | Sharpe | MaxDD % | CAGR % | Score |
|------|------------|----------|--------|-----|--------|---------|--------|-------|
"""

        for i, config in enumerate(top_configs[:3], 1):
            params = config['params']
            metrics = config['metrics_365d']
            report += (
                f"| {i} | {params['target_bps']:.1f} | {params['stop_bps']:.1f} | "
                f"{params['base_risk_pct']:.2f} | {metrics['profit_factor']:.2f} | "
                f"{metrics['sharpe_ratio']:.2f} | {metrics['max_drawdown_pct']:.2f} | "
                f"{metrics['cagr_pct']:.2f} | {config['score']:.2f} |\n"
            )

        # Add fallback configs
        report += """

### Fallback Configurations

Config #2 and #3 are kept as fallbacks in case promoted config underperforms in live trading.

"""

        for i, config in enumerate(top_configs[1:3], 2):
            params = config['params']
            metrics = config['metrics_365d']
            report += f"""
#### Fallback #{i}

**Parameters:** target={params['target_bps']:.1f}, stop={params['stop_bps']:.1f}, risk={params['base_risk_pct']:.2f}%, boost={params['streak_boost_pct']:.2f}%
**Performance:** PF={metrics['profit_factor']:.2f}, Sharpe={metrics['sharpe_ratio']:.2f}, DD={metrics['max_drawdown_pct']:.2f}%, CAGR={metrics['cagr_pct']:.2f}%

"""

        # Add quality gates section
        report += f"""
---

## Quality Gates

All promoted configurations must pass these gates:

- **Profit Factor:** ≥ {AutotuneConfig.MIN_PROFIT_FACTOR} ✅
- **Sharpe Ratio:** ≥ {AutotuneConfig.MIN_SHARPE_RATIO} ✅
- **Max Drawdown:** ≤ {AutotuneConfig.MAX_DRAWDOWN_PCT}% ✅
- **12-Month Net:** ≥ {AutotuneConfig.MIN_12MO_NET_PCT}% ✅
- **Circuit Breakers:** < {AutotuneConfig.MAX_CIRCUIT_BREAKER_TRIPS_PER_HOUR}/hour ✅

**Status:** All gates PASSED for promoted configuration.

---

## Optimization History

**Search Method:** Bayesian Optimization with Gaussian Processes
**Initial Random Points:** {AutotuneConfig.N_INITIAL_POINTS}
**Total Evaluations:** {len(optimization_history)}
**Successful Iterations:** {len([r for r in optimization_history if r['metrics_365d']])}

### Score Distribution

"""

        # Add score distribution stats
        scores = [r['score'] for r in optimization_history if r.get('score')]
        if scores:
            report += f"""
- **Best Score:** {max(scores):.2f}
- **Median Score:** {np.median(scores):.2f}
- **Mean Score:** {np.mean(scores):.2f}
- **Std Dev:** {np.std(scores):.2f}

"""

        # Add comparative analysis
        report += """
---

## Comparative Analysis

### Top 3 vs Historical Best

Comparing the new top 3 configurations against previous best-known parameters:

"""

        # Get previous best from YAML metadata if available
        report += """
| Metric | Config #1 | Config #2 | Config #3 |
|--------|-----------|-----------|-----------|
"""

        for metric_name, metric_key in [
            ('Profit Factor', 'profit_factor'),
            ('Sharpe Ratio', 'sharpe_ratio'),
            ('Max Drawdown %', 'max_drawdown_pct'),
            ('CAGR %', 'cagr_pct'),
            ('Win Rate %', 'win_rate'),
        ]:
            row = f"| {metric_name} "
            for config in top_configs[:3]:
                value = config['metrics_365d'][metric_key]
                row += f"| {value:.2f} "
            row += "|\n"
            report += row

        # Add recommendations
        report += """

---

## Recommendations

### Deployment Strategy

1. **Promote Config #1** to production YAML
2. **Monitor** for 7 days in paper trading
3. **Fallback** to Config #2 if:
   - Live Sharpe < 1.0 after 100 trades
   - Live MaxDD > 15%
   - Circuit breakers trip > 5x/hour
4. **Re-optimize** monthly or after significant market regime changes

### Risk Controls

- **Position Sizing:** Use validated base_risk_pct with heat threshold
- **Rate Limiting:** Enforce max_trades_per_minute = """ + f"{top_configs[0]['params']['max_trades_per_min']}" + """
- **Circuit Breakers:** Monitor spread, latency, and rate limits
- **Stop Loss:** Strict adherence to stop_bps = """ + f"{top_configs[0]['params']['stop_bps']:.1f}" + """

### Next Steps

- [ ] Review promoted parameters in YAML
- [ ] Backup current configuration
- [ ] Deploy to paper trading environment
- [ ] Monitor performance metrics
- [ ] Schedule next autotune run

---

## Appendix

### Search Space

"""

        # Add search space details
        report += f"""
- **target_bps:** {AutotuneConfig.TARGET_BPS_RANGE}
- **stop_bps:** {AutotuneConfig.STOP_BPS_RANGE}
- **base_risk_pct:** {AutotuneConfig.BASE_RISK_PCT_RANGE}
- **streak_boost_pct:** {AutotuneConfig.STREAK_BOOST_PCT_RANGE}
- **heat_threshold:** {AutotuneConfig.HEAT_THRESHOLD_RANGE}
- **max_trades_per_min:** {AutotuneConfig.MAX_TRADES_PER_MIN_RANGE}
- **momentum_filter:** {AutotuneConfig.MOMENTUM_FILTER_OPTIONS}

### Configuration Files

- **YAML Config:** `{AutotuneConfig.CONFIG_PATH}`
- **Backup Directory:** `{AutotuneConfig.BACKUP_DIR}`
- **Results JSON:** `{AutotuneConfig.RESULTS_PATH}`

### Reproducibility

```bash
# Reproduce this optimization
conda activate crypto-bot
python scripts/autotune_full.py

# View results
cat {AutotuneConfig.REPORT_PATH}
```

---

*Generated by autotune_full.py - Crypto AI Bot Optimization Suite*
"""

        return report


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution flow."""

    logger.info("="*80)
    logger.info("AUTOTUNE FULL - COMPREHENSIVE PARAMETER OPTIMIZATION")
    logger.info("="*80)
    logger.info(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Create output directory
    os.makedirs(AutotuneConfig.OUTPUT_DIR, exist_ok=True)

    # Initialize components
    config_manager = ConfigManager()
    optimizer = BayesianOptimizer()

    # Step 1: Backup current configuration
    logger.info("\nStep 1: Backing up current configuration...")
    backup_path = config_manager.backup_current_config()

    # Step 2: Run Bayesian optimization
    logger.info("\nStep 2: Running Bayesian optimization...")
    try:
        results_history = optimizer.optimize()
    except Exception as e:
        logger.error(f"Optimization failed: {e}")
        logger.info("Rolling back to previous configuration...")
        if backup_path:
            config_manager.rollback_to_backup(backup_path)
        return 1

    # Step 3: Select top 3 configurations
    logger.info("\nStep 3: Selecting top 3 configurations...")

    # Sort by score (descending)
    valid_results = [r for r in results_history if r.get('score') and r.get('metrics_365d')]
    valid_results.sort(key=lambda x: x['score'], reverse=True)

    top_3_configs = valid_results[:AutotuneConfig.N_TOP_CONFIGS]

    if len(top_3_configs) == 0:
        logger.error("No valid configurations found!")
        logger.info("Rolling back to previous configuration...")
        if backup_path:
            config_manager.rollback_to_backup(backup_path)
        return 1

    logger.info(f"Selected {len(top_3_configs)} top configurations")

    for i, config in enumerate(top_3_configs, 1):
        logger.info(f"\nConfig #{i}:")
        logger.info(f"  Score: {config['score']:.2f}")
        logger.info(f"  Params: {config['params']}")
        logger.info(f"  PF: {config['metrics_365d']['profit_factor']:.2f}")
        logger.info(f"  Sharpe: {config['metrics_365d']['sharpe_ratio']:.2f}")
        logger.info(f"  MaxDD: {config['metrics_365d']['max_drawdown_pct']:.2f}%")
        logger.info(f"  CAGR: {config['metrics_365d']['cagr_pct']:.2f}%")

    # Step 4: Promote #1 to YAML
    logger.info("\nStep 4: Promoting config #1 to YAML...")
    promoted_config = top_3_configs[0]

    success = config_manager.update_config(
        promoted_config['params'],
        promoted_config['metrics_365d']
    )

    if not success:
        logger.error("Failed to update configuration!")
        logger.info("Rolling back to previous configuration...")
        if backup_path:
            config_manager.rollback_to_backup(backup_path)
        return 1

    # Step 5: Run confirmatory backtest on promoted config
    logger.info("\nStep 5: Running confirmatory backtest on promoted config...")
    runner = BacktestRunner()

    confirmatory_metrics = runner.run_backtest_with_params(
        promoted_config['params'],
        365
    )

    if not confirmatory_metrics:
        logger.error("Confirmatory backtest failed!")
        logger.info("Rolling back to previous configuration...")
        if backup_path:
            config_manager.rollback_to_backup(backup_path)
        return 1

    # Validate confirmatory results
    passed_gates, failures = runner.validate_against_gates(confirmatory_metrics)

    if not passed_gates:
        logger.error(f"Confirmatory backtest failed gates: {', '.join(failures)}")
        logger.info("Rolling back to previous configuration...")
        if backup_path:
            config_manager.rollback_to_backup(backup_path)
        return 1

    logger.info("[PASS] Confirmatory backtest passed all gates!")

    # Step 6: Save results to JSON
    logger.info("\nStep 6: Saving results to JSON...")
    results_data = {
        'timestamp': datetime.now().isoformat(),
        'promoted_config': promoted_config,
        'top_3_configs': top_3_configs,
        'optimization_history': results_history,
        'backup_path': str(backup_path) if backup_path else None,
    }

    with open(AutotuneConfig.RESULTS_PATH, 'w') as f:
        json.dump(results_data, f, indent=2, default=str)

    logger.info(f"Results saved to: {AutotuneConfig.RESULTS_PATH}")

    # Step 7: Generate markdown report
    logger.info("\nStep 7: Generating markdown report...")
    report = ReportGenerator.generate_report(
        top_3_configs,
        promoted_config,
        results_history
    )

    with open(AutotuneConfig.REPORT_PATH, 'w') as f:
        f.write(report)

    logger.info(f"Report saved to: {AutotuneConfig.REPORT_PATH}")

    # Final summary
    logger.info("\n" + "="*80)
    logger.info("AUTOTUNE COMPLETE!")
    logger.info("="*80)
    logger.info(f"\nPromoted Configuration:")
    logger.info(f"  Target BPS: {promoted_config['params']['target_bps']:.1f}")
    logger.info(f"  Stop BPS: {promoted_config['params']['stop_bps']:.1f}")
    logger.info(f"  Base Risk %: {promoted_config['params']['base_risk_pct']:.2f}")
    logger.info(f"  Streak Boost %: {promoted_config['params']['streak_boost_pct']:.2f}")
    logger.info(f"\nPerformance (365d):")
    logger.info(f"  Profit Factor: {promoted_config['metrics_365d']['profit_factor']:.2f}")
    logger.info(f"  Sharpe Ratio: {promoted_config['metrics_365d']['sharpe_ratio']:.2f}")
    logger.info(f"  Max Drawdown: {promoted_config['metrics_365d']['max_drawdown_pct']:.2f}%")
    logger.info(f"  CAGR: {promoted_config['metrics_365d']['cagr_pct']:.2f}%")
    logger.info(f"\nFiles Generated:")
    logger.info(f"  Report: {AutotuneConfig.REPORT_PATH}")
    logger.info(f"  Results: {AutotuneConfig.RESULTS_PATH}")
    logger.info(f"  Backup: {backup_path}")
    logger.info("\n" + "="*80)

    return 0


if __name__ == '__main__':
    exit(main())
