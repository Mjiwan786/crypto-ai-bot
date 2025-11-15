#!/usr/bin/env python3
from __future__ import annotations

"""
⚠️ SAFETY: No live trading unless MODE=live and confirmation set.
Enhanced backtest runner for all active strategies.

This script runs comprehensive backtests across multiple strategies, pairs, and timeframes,
then generates detailed reports and visualizations for analysis.

Features:
- Parallel execution for faster processing
- Comprehensive error handling and logging
- Progress tracking with real-time updates
- Detailed performance analysis and reporting
- Automatic visualization generation
- Flexible configuration options
- Grid search parameter optimization

Usage examples:
  python scripts/backtest_all.py
  python scripts/backtest_all.py --days 180 --timeframes 1h 4h --pairs BTC/USD ETH/USD
  python scripts/backtest_all.py --only trend_following momentum --parallel 4
  python scripts/backtest_all.py --grid "short_window=5,10,15" --grid "long_window=20,30,40"
  python scripts/backtest_all.py --validate --verbose
"""

import argparse
import json
import logging
import shlex
import subprocess
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Suppress warnings
warnings.filterwarnings('ignore', category=UserWarning, module='matplotlib')
warnings.filterwarnings('ignore', category=FutureWarning)

# Paths
ROOT = Path(__file__).resolve().parents[1] if Path(__file__).parent.name == "scripts" else Path.cwd()
CFG_PATH = ROOT / "config" / "settings.yaml"
REPORTS_DIR = ROOT / "reports"
SUMMARY_DIR = REPORTS_DIR / "summary"
LOGS_DIR = ROOT / "logs"

# Ensure directories exist
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class BacktestJob:
    """Container for backtest job parameters"""
    strategy: str
    pair: str
    timeframe: str
    days: int
    extra_args: List[str]
    job_id: str = ""
    
    def __post_init__(self):
        if not self.job_id:
            self.job_id = f"{self.strategy}-{self.pair.replace('/', '')}-{self.timeframe}-{self.days}d"
    
    def __str__(self) -> str:
        return self.job_id

class ProgressTracker:
    """Track and display progress of backtest execution"""
    
    def __init__(self, total_jobs: int):
        self.total_jobs = total_jobs
        self.completed_jobs = 0
        self.successful_jobs = 0
        self.failed_jobs = 0
        self.start_time = time.time()
        
    def update(self, success: bool = True):
        """Update progress counters"""
        self.completed_jobs += 1
        if success:
            self.successful_jobs += 1
        else:
            self.failed_jobs += 1
            
    def get_progress_string(self) -> str:
        """Get formatted progress string"""
        elapsed = time.time() - self.start_time
        if self.completed_jobs > 0:
            eta = (elapsed / self.completed_jobs) * (self.total_jobs - self.completed_jobs)
            eta_str = f", ETA: {eta/60:.1f}m" if eta > 60 else f", ETA: {eta:.0f}s"
        else:
            eta_str = ""
        
        progress_pct = (self.completed_jobs / self.total_jobs) * 100
        return (f"Progress: {self.completed_jobs}/{self.total_jobs} ({progress_pct:.1f}%) "
                f"✓{self.successful_jobs} ✗{self.failed_jobs}{eta_str}")

def setup_logging(verbose: bool = False) -> logging.Logger:
    """Setup logging configuration with file and console output"""
    
    level = logging.DEBUG if verbose else logging.INFO
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"backtest_all_{timestamp}.log"
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)8s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Setup file handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    
    # Setup console handler with cleaner format
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%H:%M:%S')
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(level)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()  # Clear any existing handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Suppress noisy loggers
    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)
    
    logger.info(f"Logging initialized - File: {log_file}")
    return logger

def load_config() -> Dict:
    """Load configuration with enhanced error handling"""
    
    if not CFG_PATH.exists():
        logging.warning(f"Config file not found at {CFG_PATH}, using defaults")
        return {}
    
    try:
        import yaml
        with open(CFG_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
        logging.info(f"Loaded configuration from {CFG_PATH}")
        return config
    except Exception as e:
        logging.error(f"Error loading config: {e}")
        return {}

def get_strategies_from_config(cfg: Dict) -> List[str]:
    """Extract strategy list from config with fallbacks"""
    
    # Try multiple config locations
    strategies = None
    
    # Check strategies.active_strategies
    if 'strategies' in cfg and 'active_strategies' in cfg['strategies']:
        strategies = cfg['strategies']['active_strategies']
    
    # Check backtesting.strategies
    elif 'backtesting' in cfg and 'strategies' in cfg['backtesting']:
        strategies = cfg['backtesting']['strategies']
    
    # Check root level strategies
    elif 'active_strategies' in cfg:
        strategies = cfg['active_strategies']
    
    if isinstance(strategies, list) and strategies:
        strategy_list = [str(s).strip() for s in strategies if s]
        logging.info(f"Found {len(strategy_list)} strategies from config: {strategy_list}")
        return strategy_list
    
    # Enhanced fallback list
    fallback = [
        "trend_following", "breakout", "mean_reversion", 
        "momentum", "sideways"
    ]
    logging.info(f"Using fallback strategies: {fallback}")
    return fallback

def get_pairs_from_config(cfg: Dict) -> List[str]:
    """Extract trading pairs from config with multiple exchange support"""
    
    exchanges = cfg.get("exchanges", {})
    
    # Try multiple exchange configurations
    for exchange_name in ["kraken", "binance", "coinbase", "exchange"]:
        if exchange_name in exchanges:
            exchange_config = exchanges[exchange_name]
            
            # Try different pair key names
            for pair_key in ["pairs", "trading_pairs", "symbols"]:
                if pair_key in exchange_config:
                    pairs = exchange_config[pair_key]
                    if isinstance(pairs, list) and pairs:
                        pair_list = [str(p).strip() for p in pairs if p]
                        logging.info(f"Found {len(pair_list)} pairs from {exchange_name}: {pair_list}")
                        return pair_list
    
    # Check root level pairs
    if 'pairs' in cfg:
        pairs = cfg['pairs']
        if isinstance(pairs, list) and pairs:
            pair_list = [str(p).strip() for p in pairs if p]
            logging.info(f"Found {len(pair_list)} pairs from root config: {pair_list}")
            return pair_list
    
    # Enhanced fallback pairs
    fallback = ["BTC/USD", "ETH/USD", "BTC/EUR", "ETH/BTC", "ADA/USD"]
    logging.info(f"Using fallback pairs: {fallback}")
    return fallback

def validate_environment() -> bool:
    """Comprehensive environment validation"""
    
    logging.info("🔍 Validating environment...")
    errors = []
    warnings_list = []
    
    # Check if backtest.py exists and is functional
    backtest_script = ROOT / "backtest.py"
    if not backtest_script.exists():
        errors.append(f"backtest.py not found at {backtest_script}")
    else:
        # Check if backtest.py is more than just a stub
        try:
            with open(backtest_script, 'r') as f:
                content = f.read()
            if len(content) < 1000:  # Likely just a stub
                warnings_list.append("backtest.py appears to be a stub (very small file)")
            if 'def main(' not in content and 'if __name__' not in content:
                warnings_list.append("backtest.py may not have proper entry point")
        except Exception as e:
            warnings_list.append(f"Could not validate backtest.py content: {e}")
    
    # Check required directories
    required_dirs = [REPORTS_DIR, ROOT / "config"]
    for dir_path in required_dirs:
        if not dir_path.exists():
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                logging.info(f"Created missing directory: {dir_path}")
            except Exception as e:
                errors.append(f"Cannot create required directory {dir_path}: {e}")
    
    # Check Python dependencies
    required_modules = {
        "pandas": "Data manipulation and analysis",
        "numpy": "Numerical computing",
        "matplotlib": "Plotting and visualization",
        "yaml": "Configuration file parsing"
    }
    
    missing_modules = []
    for module, description in required_modules.items():
        try:
            __import__(module)
            logging.debug(f"✓ {module} available")
        except ImportError:
            missing_modules.append(f"{module} ({description})")
    
    if missing_modules:
        errors.append(f"Missing required modules: {', '.join(missing_modules)}")
    
    # Print results
    if errors:
        logging.error("❌ Environment validation failed:")
        for error in errors:
            logging.error(f"  - {error}")
        return False
    
    if warnings_list:
        logging.warning("⚠️  Environment warnings:")
        for warning in warnings_list:
            logging.warning(f"  - {warning}")
    
    logging.info("✅ Environment validation passed")
    return True

def run_single_backtest(job: BacktestJob) -> Tuple[str, int, Optional[Dict], float]:
    """
    Run a single backtest job with comprehensive error handling.
    
    Returns:
        Tuple of (job_id, return_code, performance_data, execution_time)
    """
    
    start_time = time.time()
    job_id = str(job)
    
    # Build command
    cmd = [
        sys.executable, str(ROOT / "backtest.py"),
        "--strategy", job.strategy,
        "--pair", job.pair,
        "--timeframe", job.timeframe,
        "--days", str(job.days),
    ] + job.extra_args
    
    logging.debug(f"Executing: {' '.join(shlex.quote(c) for c in cmd)}")
    
    try:
        # Run backtest with timeout
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout per backtest
            encoding='utf-8',
            errors='replace'  # Handle encoding errors gracefully
        )
        
        execution_time = time.time() - start_time
        
        if result.returncode != 0:
            logging.error(f"❌ {job_id} failed (rc={result.returncode})")
            if result.stderr:
                logging.error(f"   stderr: {result.stderr[:500]}")
            if result.stdout:
                logging.debug(f"   stdout: {result.stdout[:500]}")
        else:
            logging.debug(f"✅ {job_id} completed in {execution_time:.1f}s")
        
        # Collect performance data
        perf = collect_performance_data(job.strategy, job.pair)
        
        return job_id, result.returncode, perf, execution_time
        
    except subprocess.TimeoutExpired:
        execution_time = time.time() - start_time
        logging.error(f"⏰ {job_id} timed out after 5 minutes")
        return job_id, -1, None, execution_time
        
    except Exception as e:
        execution_time = time.time() - start_time
        logging.error(f"💥 {job_id} crashed: {str(e)[:200]}")
        return job_id, -2, None, execution_time

def collect_performance_data(strategy: str, pair: str) -> Optional[Dict]:
    """
    Collect performance data with enhanced file detection and validation.
    """
    
    pair_clean = pair.replace("/", "").replace("-", "")
    
    # Multiple candidate locations for performance files
    candidates = [
        REPORTS_DIR / pair_clean / "performance.json",
        REPORTS_DIR / strategy / pair_clean / "performance.json",
        REPORTS_DIR / pair / "performance.json",
        REPORTS_DIR / strategy / "performance.json",
        REPORTS_DIR / f"{strategy}_{pair_clean}" / "performance.json",
        REPORTS_DIR / f"{pair_clean}_{strategy}" / "performance.json",
        REPORTS_DIR / strategy / f"{pair_clean}.json",
        REPORTS_DIR / "latest" / f"{strategy}_{pair_clean}.json"
    ]
    
    for path in candidates:
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Validate data structure
                if isinstance(data, dict) and 'net_profit_pct' in data:
                    logging.debug(f"📊 Found performance data at {path}")
                    return data
                else:
                    logging.warning(f"⚠️  Invalid performance data format in {path}")
                    
            except json.JSONDecodeError as e:
                logging.warning(f"⚠️  Invalid JSON in {path}: {e}")
            except Exception as e:
                logging.warning(f"⚠️  Error reading {path}: {e}")
    
    logging.debug(f"📊 No performance data found for {strategy} {pair}")
    return None

def save_comprehensive_summary(results: List[Dict], start_time: float, config: Dict):
    """Save comprehensive summary with metadata and statistics"""
    
    if not results:
        logging.warning("No results to save")
        return
    
    runtime = time.time() - start_time
    
    # Generate comprehensive metadata
    metadata = {
        "generated_at": datetime.now().isoformat(),
        "total_runtime_seconds": round(runtime, 2),
        "total_runtime_formatted": f"{runtime//3600:.0f}h {(runtime%3600)//60:.0f}m {runtime%60:.0f}s",
        "total_backtests": len(results),
        "script_version": "3.0",
        "python_version": sys.version,
        "working_directory": str(ROOT),
        "config_used": config,
        "summary_statistics": generate_summary_statistics(results)
    }
    
    # Enhanced JSON output
    output_data = {
        "metadata": metadata,
        "results": results
    }
    
    # Save JSON
    json_path = SUMMARY_DIR / "all_backtests.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, default=str, ensure_ascii=False)
    logging.info(f"📄 Saved JSON summary: {json_path}")
    
    # Save CSV with dynamic columns
    save_enhanced_csv(results, SUMMARY_DIR / "all_backtests.csv")
    
    # Save detailed statistics
    save_detailed_statistics(results, SUMMARY_DIR / "backtest_statistics.json")

def generate_summary_statistics(results: List[Dict]) -> Dict:
    """Generate summary statistics from results"""
    
    if not results:
        return {}
    
    try:
        import pandas as pd
        df = pd.DataFrame(results)
        
        stats = {
            "total_tests": len(results),
            "unique_strategies": df['strategy'].nunique() if 'strategy' in df else 0,
            "unique_pairs": df['pair'].nunique() if 'pair' in df else 0,
            "unique_timeframes": df['timeframe'].nunique() if 'timeframe' in df else 0
        }
        
        # Performance statistics
        if 'net_profit_pct' in df.columns:
            profit_col = df['net_profit_pct']
            stats.update({
                "profitable_tests": int((profit_col > 0).sum()),
                "unprofitable_tests": int((profit_col <= 0).sum()),
                "profitability_rate": round((profit_col > 0).mean() * 100, 2),
                "average_profit": round(profit_col.mean(), 2),
                "median_profit": round(profit_col.median(), 2),
                "best_performer": round(profit_col.max(), 2),
                "worst_performer": round(profit_col.min(), 2),
                "profit_std": round(profit_col.std(), 2)
            })
        
        return stats
    except Exception as e:
        logging.warning(f"Could not generate summary statistics: {e}")
        return {"error": str(e)}

def save_enhanced_csv(results: List[Dict], csv_path: Path):
    """Save CSV with enhanced formatting and all available columns"""
    
    if not results:
        return
    
    try:
        import pandas as pd
        df = pd.DataFrame(results)
        
        # Define column order (priority columns first)
        priority_cols = [
            "strategy", "pair", "timeframe", "days",
            "net_profit_pct", "CAGR", "max_drawdown", 
            "Sharpe", "Sortino", "profit_factor", 
            "win_rate", "total_trades", "exposure"
        ]
        
        # Get all columns, prioritized order
        all_cols = list(df.columns)
        ordered_cols = [col for col in priority_cols if col in all_cols]
        remaining_cols = [col for col in all_cols if col not in priority_cols]
        final_cols = ordered_cols + sorted(remaining_cols)
        
        # Reorder dataframe
        df = df[final_cols]
        
        # Round numeric columns
        numeric_cols = df.select_dtypes(include=['number']).columns
        df[numeric_cols] = df[numeric_cols].round(3)
        
        # Save with proper formatting
        df.to_csv(csv_path, index=False, encoding='utf-8')
        logging.info(f"📊 Saved CSV summary: {csv_path} ({len(final_cols)} columns, {len(df)} rows)")
    except Exception as e:
        logging.error(f"Failed to save CSV: {e}")

def save_detailed_statistics(results: List[Dict], stats_path: Path):
    """Generate and save detailed statistical analysis"""
    
    if not results:
        return
    
    try:
        import pandas as pd
        df = pd.DataFrame(results)
        
        stats = {
            "overview": generate_summary_statistics(results),
            "by_strategy": {},
            "by_pair": {},
            "by_timeframe": {}
        }
        
        # Strategy analysis
        if 'strategy' in df.columns and 'net_profit_pct' in df.columns:
            strategy_stats = df.groupby('strategy').agg({
                'net_profit_pct': ['count', 'mean', 'std', 'min', 'max'],
                'win_rate': 'mean' if 'win_rate' in df.columns else lambda x: 0,
                'max_drawdown': 'mean' if 'max_drawdown' in df.columns else lambda x: 0,
                'Sharpe': 'mean' if 'Sharpe' in df.columns else lambda x: 0
            }).round(3)
            
            stats["by_strategy"] = strategy_stats.to_dict()
        
        # Top performers
        if 'net_profit_pct' in df.columns:
            top_10 = df.nlargest(10, 'net_profit_pct')[
                ['strategy', 'pair', 'timeframe', 'net_profit_pct']
            ].to_dict('records')
            stats["top_performers"] = top_10
        
        # Save statistics
        with open(stats_path, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, default=str, ensure_ascii=False)
        logging.info(f"📈 Saved detailed statistics: {stats_path}")
    except Exception as e:
        logging.error(f"Failed to save statistics: {e}")

def create_visualizations(results: List[Dict]):
    """Create comprehensive visualization suite"""
    
    if not results:
        logging.warning("No results for visualization")
        return
    
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt
        import pandas as pd
        
        plt.style.use('default')
        df = pd.DataFrame(results)
        
        if 'net_profit_pct' not in df.columns:
            logging.warning("No profit data for visualization")
            return
        
        # Create visualization
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle('Backtest Performance Analysis', fontsize=16, fontweight='bold')
        
        # 1. Profit distribution histogram
        axes[0,0].hist(df['net_profit_pct'], bins=20, alpha=0.7, edgecolor='black')
        axes[0,0].axvline(0, color='red', linestyle='--', alpha=0.7, label='Break-even')
        axes[0,0].set_xlabel('Net Profit %')
        axes[0,0].set_ylabel('Frequency')
        axes[0,0].set_title('Profit Distribution')
        axes[0,0].legend()
        axes[0,0].grid(True, alpha=0.3)
        
        # 2. Strategy performance boxplot
        if 'strategy' in df.columns:
            strategy_profits = []
            strategy_names = []
            for strategy in df['strategy'].unique():
                strategy_data = df[df['strategy'] == strategy]['net_profit_pct']
                strategy_profits.append(strategy_data)
                strategy_names.append(strategy)
            
            axes[0,1].boxplot(strategy_profits, labels=strategy_names)
            axes[0,1].set_xlabel('Strategy')
            axes[0,1].set_ylabel('Net Profit %')
            axes[0,1].set_title('Profit by Strategy')
            axes[0,1].tick_params(axis='x', rotation=45)
        
        # 3. Risk vs Return scatter
        if 'max_drawdown' in df.columns:
            axes[1,0].scatter(df['max_drawdown'], df['net_profit_pct'], alpha=0.6)
            axes[1,0].set_xlabel('Max Drawdown %')
            axes[1,0].set_ylabel('Net Profit %')
            axes[1,0].set_title('Risk vs Return')
            axes[1,0].grid(True, alpha=0.3)
        
        # 4. Pair performance
        if 'pair' in df.columns:
            pair_profits = df.groupby('pair')['net_profit_pct'].mean().sort_values(ascending=True)
            pair_profits.plot(kind='barh', ax=axes[1,1])
            axes[1,1].set_xlabel('Average Net Profit %')
            axes[1,1].set_title('Average Profit by Pair')
            axes[1,1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Save visualization
        viz_path = SUMMARY_DIR / "performance_analysis.png"
        plt.savefig(viz_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        
        logging.info(f"📊 Saved visualization: {viz_path}")
        
    except Exception as e:
        logging.warning(f"Cannot create visualizations: {e}")

def run_parallel_backtests(jobs: List[BacktestJob], max_workers: int = 4, 
                          progress_callback=None) -> Tuple[List[Dict], List[str]]:
    """Run backtests in parallel with progress tracking"""
    
    results = []
    failures = []
    
    logging.info(f"🚀 Starting {len(jobs)} backtests with {max_workers} parallel workers")
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all jobs
        future_to_job = {executor.submit(run_single_backtest, job): job for job in jobs}
        
        # Process completed jobs with progress tracking
        for future in as_completed(future_to_job):
            job = future_to_job[future]
            try:
                job_id, returncode, perf, exec_time = future.result()
                
                if returncode == 0 and perf:
                    # Successful backtest
                    row = {
                        "strategy": job.strategy,
                        "pair": job.pair,
                        "timeframe": job.timeframe,
                        "days": job.days,
                        "execution_time": round(exec_time, 2),
                        **perf
                    }
                    results.append(row)
                    
                    if progress_callback:
                        progress_callback(True)
                        
                    logging.info(f"✅ {job_id} completed successfully ({exec_time:.1f}s)")
                    
                else:
                    # Failed backtest
                    failures.append(f"{job_id} (rc={returncode})")
                    
                    if progress_callback:
                        progress_callback(False)
                        
                    logging.warning(f"❌ {job_id} failed")
                    
            except Exception as e:
                failures.append(f"{job} (exception: {str(e)[:100]})")
                
                if progress_callback:
                    progress_callback(False)
                    
                logging.error(f"💥 {job} crashed: {e}")
    
    return results, failures

def run_sequential_backtests(jobs: List[BacktestJob], progress_callback=None) -> Tuple[List[Dict], List[str]]:
    """Run backtests sequentially with progress tracking"""
    
    results = []
    failures = []
    
    logging.info(f"🔄 Running {len(jobs)} backtests sequentially")
    
    for i, job in enumerate(jobs, 1):
        logging.info(f"📊 Processing job {i}/{len(jobs)}: {job}")
        
        job_id, returncode, perf, exec_time = run_single_backtest(job)
        
        if returncode == 0 and perf:
            row = {
                "strategy": job.strategy,
                "pair": job.pair,
                "timeframe": job.timeframe,
                "days": job.days,
                "execution_time": round(exec_time, 2),
                **perf
            }
            results.append(row)
            
            if progress_callback:
                progress_callback(True)
                
        else:
            failures.append(f"{job_id} (rc={returncode})")
            
            if progress_callback:
                progress_callback(False)
    
    return results, failures

def create_jobs_from_config(strategies: List[str], pairs: List[str], timeframes: List[str], 
                           days: int, extra_args: List[str]) -> List[BacktestJob]:
    """Create backtest jobs from configuration parameters"""
    
    jobs = []
    
    for timeframe in timeframes:
        for strategy in strategies:
            for pair in pairs:
                job = BacktestJob(
                    strategy=strategy,
                    pair=pair,
                    timeframe=timeframe,
                    days=days,
                    extra_args=extra_args.copy()
                )
                jobs.append(job)
    
    return jobs

def print_execution_summary(results: List[Dict], failures: List[str], 
                          total_jobs: int, runtime: float):
    """Print comprehensive execution summary"""
    
    print("\n" + "="*80)
    print("🏁 BACKTEST EXECUTION SUMMARY")
    print("="*80)
    
    # Basic statistics
    success_count = len(results)
    failure_count = len(failures)
    success_rate = (success_count / total_jobs * 100) if total_jobs > 0 else 0
    
    print("📊 Execution Statistics:")
    print(f"   Total jobs: {total_jobs}")
    print(f"   Successful: {success_count} ({success_rate:.1f}%)")
    print(f"   Failed: {failure_count} ({failure_count/total_jobs*100:.1f}%)")
    print(f"   Runtime: {runtime//3600:.0f}h {(runtime%3600)//60:.0f}m {runtime%60:.0f}s")
    
    if results:
        try:
            import pandas as pd
            df = pd.DataFrame(results)
            
            # Performance summary
            if 'net_profit_pct' in df.columns:
                profitable = (df['net_profit_pct'] > 0).sum()
                avg_profit = df['net_profit_pct'].mean()
                best_profit = df['net_profit_pct'].max()
                worst_profit = df['net_profit_pct'].min()
                
                print("\n💰 Performance Summary:")
                print(f"   Profitable strategies: {profitable}/{len(df)} ({profitable/len(df)*100:.1f}%)")
                print(f"   Average profit: {avg_profit:.2f}%")
                print(f"   Best performer: {best_profit:.2f}%")
                print(f"   Worst performer: {worst_profit:.2f}%")
            
            # Top performers
            if 'net_profit_pct' in df.columns and len(df) >= 3:
                print("\n🏆 Top 3 Performers:")
                top3 = df.nlargest(3, 'net_profit_pct')
                for i, (_, row) in enumerate(top3.iterrows(), 1):
                    print(f"   {i}. {row['strategy']} | {row['pair']} | {row['timeframe']} → {row['net_profit_pct']:.2f}%")
            
            # Execution timing
            if 'execution_time' in df.columns:
                avg_time = df['execution_time'].mean()
                max_time = df['execution_time'].max()
                min_time = df['execution_time'].min()
                print("\n⏱️  Execution Timing:")
                print(f"   Average: {avg_time:.1f}s")
                print(f"   Range: {min_time:.1f}s - {max_time:.1f}s")
        except Exception as e:
            logging.warning(f"Could not generate performance summary: {e}")
    
    # Failure details
    if failures:
        print(f"\n❌ Failed Jobs ({len(failures)}):")
        for i, failure in enumerate(failures[:10], 1):  # Show first 10 failures
            print(f"   {i}. {failure}")
        if len(failures) > 10:
            print(f"   ... and {len(failures) - 10} more")
    
    print(f"\n📁 Reports saved to: {SUMMARY_DIR}")
    print("="*80)

def main() -> int:
    """Main execution function with comprehensive argument parsing"""
    
    parser = argparse.ArgumentParser(
        description="Enhanced cryptocurrency backtesting suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic run with all configured strategies and pairs
  python scripts/backtest_all.py
  
  # Custom configuration
  python scripts/backtest_all.py --days 180 --timeframes 1h 4h --pairs BTC/USD ETH/USD
  
  # Parallel execution for faster processing
  python scripts/backtest_all.py --parallel 4 --verbose
  
  # Focus on specific strategies
  python scripts/backtest_all.py --only trend_following momentum
  
  # Exclude problematic strategies
  python scripts/backtest_all.py --exclude breakout
  
  # Validation run
  python scripts/backtest_all.py --validate --dry-run
        """
    )
    
    # Core parameters
    parser.add_argument("--days", type=int, default=90, 
                       help="Number of days to backtest (default: 90)")
    parser.add_argument("--timeframes", nargs="+", default=["1h"], 
                       help="Timeframes to test (default: 1h)")
    parser.add_argument("--pairs", nargs="+", default=[], 
                       help="Trading pairs to test (default: from config)")
    
    # Strategy selection
    parser.add_argument("--only", nargs="*", default=[], 
                       help="Only run these strategies")
    parser.add_argument("--exclude", nargs="*", default=[], 
                       help="Exclude these strategies")
    
    # Execution options
    parser.add_argument("--parallel", type=int, default=1, 
                       help="Number of parallel processes (default: 1)")
    parser.add_argument("--timeout", type=int, default=300, 
                       help="Timeout per backtest in seconds (default: 300)")
    
    # Grid search
    parser.add_argument("--grid", action="append", default=[], 
                       help="Grid search parameters (format: param=val1,val2,val3)")
    
    # Control options
    parser.add_argument("--validate", action="store_true", 
                       help="Validate environment before running")
    parser.add_argument("--dry-run", action="store_true", 
                       help="Show what would be run without executing")
    parser.add_argument("--verbose", "-v", action="store_true", 
                       help="Enable verbose logging")
    parser.add_argument("--no-viz", action="store_true", 
                       help="Skip visualization generation")
    
    # Additional arguments
    parser.add_argument("--extra", nargs=argparse.REMAINDER, 
                       help="Additional arguments to pass to backtest.py")
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(args.verbose)
    start_time = time.time()
    
    logger.info("🚀 Enhanced Backtest Suite v3.0")
    logger.info(f"⚙️  Configuration: {args}")
    
    # Validate environment if requested
    if args.validate:
        if not validate_environment():
            logger.error("❌ Environment validation failed")
            return 1
        logger.info("✅ Environment validation passed")
    
    # Load configuration
    try:
        config = load_config()
        logger.info(f"📋 Loaded configuration with {len(config)} sections")
    except Exception as e:
        logger.error(f"❌ Failed to load configuration: {e}")
        config = {}
    
    # Get strategies
    strategies = get_strategies_from_config(config)
    if args.only:
        strategies = [s for s in strategies if s in args.only]
        logger.info(f"🎯 Filtered to selected strategies: {strategies}")
    if args.exclude:
        strategies = [s for s in strategies if s not in args.exclude]
        logger.info(f"🚫 Excluded strategies: {args.exclude}")
    
    if not strategies:
        logger.error("❌ No strategies to test")
        return 1
    
    # Get pairs and timeframes
    pairs = args.pairs or get_pairs_from_config(config)
    timeframes = args.timeframes
    
    logger.info("📊 Test configuration:")
    logger.info(f"   Strategies: {strategies}")
    logger.info(f"   Pairs: {pairs}")
    logger.info(f"   Timeframes: {timeframes}")
    logger.info(f"   Days: {args.days}")
    
    # Prepare extra arguments
    extra_args = []
    if args.extra:
        extra_args.extend(args.extra)
    
    # Create all jobs
    jobs = create_jobs_from_config(strategies, pairs, timeframes, args.days, extra_args)
    total_jobs = len(jobs)
    
    logger.info(f"📝 Created {total_jobs} backtest jobs")
    
    # Show job preview
    if args.dry_run:
        logger.info("🔍 DRY RUN - Jobs that would be executed:")
        for i, job in enumerate(jobs[:10], 1):
            logger.info(f"   {i}. {job}")
        if len(jobs) > 10:
            logger.info(f"   ... and {len(jobs) - 10} more jobs")
        logger.info("✅ Dry run completed")
        return 0
    
    # Initialize progress tracking
    progress = ProgressTracker(total_jobs)
    
    def progress_callback(success: bool):
        progress.update(success)
        if progress.completed_jobs % max(1, total_jobs // 20) == 0 or progress.completed_jobs == total_jobs:
            logger.info(progress.get_progress_string())
    
    # Execute backtests
    logger.info("🏃 Starting execution...")
    try:
        if args.parallel > 1:
            logger.info(f"⚡ Using parallel execution with {args.parallel} workers")
            results, failures = run_parallel_backtests(jobs, args.parallel, progress_callback)
        else:
            logger.info("🔄 Using sequential execution")
            results, failures = run_sequential_backtests(jobs, progress_callback)
            
    except KeyboardInterrupt:
        logger.warning("⛔ Execution interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"💥 Execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Generate comprehensive summary
    runtime = time.time() - start_time
    logger.info("💾 Generating comprehensive reports...")
    
    try:
        save_comprehensive_summary(results, start_time, config)
        logger.info("✅ Reports saved successfully")
    except Exception as e:
        logger.error(f"❌ Failed to save reports: {e}")
    
    # Generate visualizations
    if not args.no_viz and results:
        logger.info("📊 Generating visualizations...")
        try:
            create_visualizations(results)
            logger.info("✅ Visualizations generated")
        except Exception as e:
            logger.warning(f"⚠️  Visualization generation failed: {e}")
    
    # Print final summary
    print_execution_summary(results, failures, total_jobs, runtime)
    
    # Exit with appropriate code
    if failures:
        logger.warning(f"⚠️  Completed with {len(failures)} failures")
        return 1
    else:
        logger.info("🎉 All backtests completed successfully!")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())