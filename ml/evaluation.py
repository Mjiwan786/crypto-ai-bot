"""
Evaluation Metrics and Cross-Validation for Trading ML Models.

Implements trading-specific metrics (win rate, Sharpe ratio, max drawdown)
and time-series cross-validation for backtesting.

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, classification_report
)
from sklearn.model_selection import TimeSeriesSplit
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TradingMetrics:
    """
    Calculate trading-specific performance metrics.

    Metrics include:
    - Win rate
    - Profit factor
    - Sharpe ratio
    - Sortino ratio
    - Maximum drawdown
    - Calmar ratio
    - Average trade return
    """

    def __init__(self, risk_free_rate: float = 0.0):
        """
        Args:
            risk_free_rate: Annual risk-free rate for Sharpe calculation (default 0%)
        """
        self.risk_free_rate = risk_free_rate

    def calculate_returns(self,
                         predictions: np.ndarray,
                         actual_returns: np.ndarray) -> np.ndarray:
        """
        Calculate trading returns based on predictions.

        Args:
            predictions: Predicted signals (0=SHORT, 1=NEUTRAL, 2=LONG)
            actual_returns: Actual market returns (forward returns)

        Returns:
            Strategy returns array
        """
        # Map predictions to positions: SHORT=-1, NEUTRAL=0, LONG=+1
        positions = predictions - 1  # [0,1,2] -> [-1,0,1]

        # Strategy returns = position * actual_returns
        strategy_returns = positions * actual_returns

        return strategy_returns

    def win_rate(self, returns: np.ndarray) -> float:
        """
        Calculate win rate (% of profitable trades).

        Args:
            returns: Array of trade returns

        Returns:
            Win rate (0-1)
        """
        # Only count trades where position != 0
        trades = returns[returns != 0]
        if len(trades) == 0:
            return 0.0

        wins = (trades > 0).sum()
        return wins / len(trades)

    def profit_factor(self, returns: np.ndarray) -> float:
        """
        Calculate profit factor (gross profit / gross loss).

        Args:
            returns: Array of trade returns

        Returns:
            Profit factor (higher is better, > 1 is profitable)
        """
        trades = returns[returns != 0]
        if len(trades) == 0:
            return 0.0

        gross_profit = trades[trades > 0].sum()
        gross_loss = abs(trades[trades < 0].sum())

        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    def sharpe_ratio(self,
                    returns: np.ndarray,
                    periods_per_year: int = 252) -> float:
        """
        Calculate Sharpe ratio (risk-adjusted returns).

        Args:
            returns: Array of returns
            periods_per_year: Number of periods per year (252 for daily)

        Returns:
            Annualized Sharpe ratio
        """
        if len(returns) == 0 or returns.std() == 0:
            return 0.0

        # Annualized return and volatility
        mean_return = returns.mean() * periods_per_year
        std_return = returns.std() * np.sqrt(periods_per_year)

        sharpe = (mean_return - self.risk_free_rate) / std_return
        return sharpe

    def sortino_ratio(self,
                     returns: np.ndarray,
                     periods_per_year: int = 252) -> float:
        """
        Calculate Sortino ratio (downside risk-adjusted returns).

        Args:
            returns: Array of returns
            periods_per_year: Number of periods per year

        Returns:
            Annualized Sortino ratio
        """
        if len(returns) == 0:
            return 0.0

        # Downside deviation (only negative returns)
        downside_returns = returns[returns < 0]
        if len(downside_returns) == 0:
            return float('inf') if returns.mean() > 0 else 0.0

        downside_std = downside_returns.std() * np.sqrt(periods_per_year)
        if downside_std == 0:
            return 0.0

        mean_return = returns.mean() * periods_per_year
        sortino = (mean_return - self.risk_free_rate) / downside_std

        return sortino

    def max_drawdown(self, returns: np.ndarray) -> Tuple[float, int, int]:
        """
        Calculate maximum drawdown.

        Args:
            returns: Array of returns

        Returns:
            Tuple of (max_drawdown, start_idx, end_idx)
        """
        if len(returns) == 0:
            return 0.0, 0, 0

        # Calculate cumulative returns
        cumulative = (1 + returns).cumprod()

        # Calculate running maximum
        running_max = np.maximum.accumulate(cumulative)

        # Calculate drawdown
        drawdown = (cumulative - running_max) / running_max

        # Find maximum drawdown
        max_dd = drawdown.min()
        end_idx = drawdown.argmin()

        # Find start of drawdown (last peak before max drawdown)
        start_idx = cumulative[:end_idx].argmax() if end_idx > 0 else 0

        return abs(max_dd), start_idx, end_idx

    def calmar_ratio(self,
                    returns: np.ndarray,
                    periods_per_year: int = 252) -> float:
        """
        Calculate Calmar ratio (return / max drawdown).

        Args:
            returns: Array of returns
            periods_per_year: Number of periods per year

        Returns:
            Calmar ratio
        """
        if len(returns) == 0:
            return 0.0

        annualized_return = returns.mean() * periods_per_year
        max_dd, _, _ = self.max_drawdown(returns)

        if max_dd == 0:
            return float('inf') if annualized_return > 0 else 0.0

        return annualized_return / max_dd

    def calculate_all_metrics(self,
                             predictions: np.ndarray,
                             actual_returns: np.ndarray,
                             periods_per_year: int = 252) -> Dict[str, float]:
        """
        Calculate all trading metrics.

        Args:
            predictions: Predicted signals
            actual_returns: Actual market returns
            periods_per_year: Periods per year for annualization

        Returns:
            Dictionary of all metrics
        """
        # Calculate strategy returns
        strategy_returns = self.calculate_returns(predictions, actual_returns)

        # Calculate metrics
        max_dd, dd_start, dd_end = self.max_drawdown(strategy_returns)

        metrics = {
            'total_return': strategy_returns.sum(),
            'annualized_return': strategy_returns.mean() * periods_per_year,
            'win_rate': self.win_rate(strategy_returns),
            'profit_factor': self.profit_factor(strategy_returns),
            'sharpe_ratio': self.sharpe_ratio(strategy_returns, periods_per_year),
            'sortino_ratio': self.sortino_ratio(strategy_returns, periods_per_year),
            'max_drawdown': max_dd,
            'calmar_ratio': self.calmar_ratio(strategy_returns, periods_per_year),
            'avg_return': strategy_returns.mean(),
            'volatility': strategy_returns.std() * np.sqrt(periods_per_year),
            'num_trades': (strategy_returns != 0).sum(),
            'avg_win': strategy_returns[strategy_returns > 0].mean() if (strategy_returns > 0).any() else 0,
            'avg_loss': strategy_returns[strategy_returns < 0].mean() if (strategy_returns < 0).any() else 0
        }

        return metrics


class MLMetrics:
    """
    Machine learning classification metrics.

    Standard metrics for model evaluation:
    - Accuracy, Precision, Recall, F1
    - Confusion matrix
    - Per-class metrics
    """

    def __init__(self, class_labels: List[str] = None):
        """
        Args:
            class_labels: List of class label names
        """
        self.class_labels = class_labels or ['SHORT', 'NEUTRAL', 'LONG']

    def calculate_metrics(self,
                         y_true: np.ndarray,
                         y_pred: np.ndarray) -> Dict:
        """
        Calculate classification metrics.

        Args:
            y_true: True labels
            y_pred: Predicted labels

        Returns:
            Dictionary of metrics
        """
        # Overall metrics
        accuracy = accuracy_score(y_true, y_pred)
        precision = precision_score(y_true, y_pred, average='weighted', zero_division=0)
        recall = recall_score(y_true, y_pred, average='weighted', zero_division=0)
        f1 = f1_score(y_true, y_pred, average='weighted', zero_division=0)

        # Per-class metrics
        precision_per_class = precision_score(y_true, y_pred, average=None, zero_division=0)
        recall_per_class = recall_score(y_true, y_pred, average=None, zero_division=0)
        f1_per_class = f1_score(y_true, y_pred, average=None, zero_division=0)

        # Confusion matrix
        cm = confusion_matrix(y_true, y_pred)

        metrics = {
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1_score': f1,
            'confusion_matrix': cm.tolist(),
            'per_class': {
                self.class_labels[i]: {
                    'precision': precision_per_class[i],
                    'recall': recall_per_class[i],
                    'f1_score': f1_per_class[i]
                }
                for i in range(len(self.class_labels))
            }
        }

        return metrics

    def print_report(self, y_true: np.ndarray, y_pred: np.ndarray) -> None:
        """
        Print detailed classification report.

        Args:
            y_true: True labels
            y_pred: Predicted labels
        """
        print("\nClassification Report:")
        print("=" * 60)
        print(classification_report(
            y_true, y_pred,
            target_names=self.class_labels,
            zero_division=0
        ))

        print("\nConfusion Matrix:")
        print("-" * 60)
        cm = confusion_matrix(y_true, y_pred)
        print(f"{'':12s} " + " ".join(f"{label:>10s}" for label in self.class_labels))
        for i, label in enumerate(self.class_labels):
            print(f"{label:12s} " + " ".join(f"{cm[i, j]:10d}" for j in range(len(self.class_labels))))


class TimeSeriesCrossValidator:
    """
    Time series cross-validation for backtesting.

    Uses expanding window or rolling window approach to respect temporal ordering.
    """

    def __init__(self,
                 n_splits: int = 5,
                 test_size: Optional[int] = None,
                 gap: int = 0):
        """
        Args:
            n_splits: Number of splits
            test_size: Size of test set (None = automatic)
            gap: Gap between train and test to avoid lookahead bias
        """
        self.n_splits = n_splits
        self.test_size = test_size
        self.gap = gap

    def split(self, X: np.ndarray) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        Generate train/test indices for cross-validation.

        Args:
            X: Input array (to get length)

        Returns:
            List of (train_indices, test_indices) tuples
        """
        tscv = TimeSeriesSplit(
            n_splits=self.n_splits,
            test_size=self.test_size,
            gap=self.gap
        )

        splits = []
        for train_idx, test_idx in tscv.split(X):
            splits.append((train_idx, test_idx))

        return splits

    def cross_validate(self,
                      model,
                      X: np.ndarray,
                      y: np.ndarray,
                      returns: Optional[np.ndarray] = None,
                      verbose: bool = True) -> Dict:
        """
        Perform time series cross-validation.

        Args:
            model: Model with fit() and predict() methods
            X: Features
            y: Labels
            returns: Actual returns for trading metrics
            verbose: Print progress

        Returns:
            Dictionary of cross-validation results
        """
        splits = self.split(X)

        ml_metrics_calculator = MLMetrics()
        trading_metrics_calculator = TradingMetrics()

        fold_results = []

        for fold_idx, (train_idx, test_idx) in enumerate(splits):
            if verbose:
                logger.info(f"Fold {fold_idx + 1}/{len(splits)}: "
                          f"Train={len(train_idx)}, Test={len(test_idx)}")

            # Split data
            X_train, X_test = X[train_idx], X[test_idx]
            y_train, y_test = y[train_idx], y[test_idx]

            # Train model
            model.fit(X_train, y_train)

            # Predict
            y_pred = model.predict(X_test)

            # Calculate ML metrics
            ml_metrics = ml_metrics_calculator.calculate_metrics(y_test, y_pred)

            # Calculate trading metrics if returns provided
            trading_metrics = {}
            if returns is not None:
                test_returns = returns[test_idx]
                trading_metrics = trading_metrics_calculator.calculate_all_metrics(
                    y_pred, test_returns
                )

            fold_results.append({
                'fold': fold_idx + 1,
                'ml_metrics': ml_metrics,
                'trading_metrics': trading_metrics,
                'train_size': len(train_idx),
                'test_size': len(test_idx)
            })

        # Aggregate results
        aggregated = self._aggregate_results(fold_results)

        return {
            'fold_results': fold_results,
            'aggregated': aggregated
        }

    def _aggregate_results(self, fold_results: List[Dict]) -> Dict:
        """
        Aggregate cross-validation results across folds.

        Args:
            fold_results: List of fold results

        Returns:
            Aggregated metrics
        """
        # ML metrics
        ml_metrics_list = [f['ml_metrics'] for f in fold_results]
        ml_aggregated = {
            'accuracy': np.mean([m['accuracy'] for m in ml_metrics_list]),
            'precision': np.mean([m['precision'] for m in ml_metrics_list]),
            'recall': np.mean([m['recall'] for m in ml_metrics_list]),
            'f1_score': np.mean([m['f1_score'] for m in ml_metrics_list]),
            'std_accuracy': np.std([m['accuracy'] for m in ml_metrics_list]),
            'std_precision': np.std([m['precision'] for m in ml_metrics_list]),
            'std_recall': np.std([m['recall'] for m in ml_metrics_list]),
            'std_f1_score': np.std([m['f1_score'] for m in ml_metrics_list])
        }

        # Trading metrics (if available)
        trading_aggregated = {}
        if fold_results[0]['trading_metrics']:
            trading_metrics_list = [f['trading_metrics'] for f in fold_results]
            metric_keys = trading_metrics_list[0].keys()

            for key in metric_keys:
                values = [m[key] for m in trading_metrics_list]
                trading_aggregated[f'{key}_mean'] = np.mean(values)
                trading_aggregated[f'{key}_std'] = np.std(values)

        return {
            'ml_metrics': ml_aggregated,
            'trading_metrics': trading_aggregated
        }


class BacktestEvaluator:
    """
    Complete backtesting evaluation pipeline.

    Combines ML metrics and trading metrics with visualization helpers.
    """

    def __init__(self, class_labels: List[str] = None):
        """
        Args:
            class_labels: List of class label names
        """
        self.ml_metrics = MLMetrics(class_labels=class_labels)
        self.trading_metrics = TradingMetrics()

    def evaluate(self,
                y_true: np.ndarray,
                y_pred: np.ndarray,
                y_proba: Optional[np.ndarray] = None,
                actual_returns: Optional[np.ndarray] = None,
                timestamps: Optional[pd.DatetimeIndex] = None) -> Dict:
        """
        Complete evaluation with all metrics.

        Args:
            y_true: True labels
            y_pred: Predicted labels
            y_proba: Predicted probabilities (optional)
            actual_returns: Actual market returns
            timestamps: Timestamps for returns

        Returns:
            Complete evaluation results
        """
        results = {}

        # ML metrics
        results['ml_metrics'] = self.ml_metrics.calculate_metrics(y_true, y_pred)

        # Trading metrics
        if actual_returns is not None:
            results['trading_metrics'] = self.trading_metrics.calculate_all_metrics(
                y_pred, actual_returns
            )

            # Equity curve
            strategy_returns = self.trading_metrics.calculate_returns(y_pred, actual_returns)
            equity_curve = (1 + strategy_returns).cumprod()

            results['equity_curve'] = equity_curve
            if timestamps is not None:
                results['equity_curve_df'] = pd.DataFrame({
                    'timestamp': timestamps,
                    'equity': equity_curve,
                    'returns': strategy_returns
                })

        # Probability statistics
        if y_proba is not None:
            results['probability_stats'] = {
                'mean_confidence': y_proba.max(axis=1).mean(),
                'std_confidence': y_proba.max(axis=1).std(),
                'min_confidence': y_proba.max(axis=1).min(),
                'max_confidence': y_proba.max(axis=1).max()
            }

        return results

    def print_summary(self, results: Dict) -> None:
        """
        Print evaluation summary.

        Args:
            results: Evaluation results dictionary
        """
        print("\n" + "=" * 70)
        print("BACKTEST EVALUATION SUMMARY")
        print("=" * 70)

        # ML Metrics
        if 'ml_metrics' in results:
            print("\nMachine Learning Metrics:")
            print("-" * 70)
            ml = results['ml_metrics']
            print(f"  Accuracy:  {ml['accuracy']:.4f}")
            print(f"  Precision: {ml['precision']:.4f}")
            print(f"  Recall:    {ml['recall']:.4f}")
            print(f"  F1 Score:  {ml['f1_score']:.4f}")

        # Trading Metrics
        if 'trading_metrics' in results:
            print("\nTrading Metrics:")
            print("-" * 70)
            tm = results['trading_metrics']
            print(f"  Total Return:      {tm['total_return']:>10.2%}")
            print(f"  Annualized Return: {tm['annualized_return']:>10.2%}")
            print(f"  Sharpe Ratio:      {tm['sharpe_ratio']:>10.3f}")
            print(f"  Sortino Ratio:     {tm['sortino_ratio']:>10.3f}")
            print(f"  Max Drawdown:      {tm['max_drawdown']:>10.2%}")
            print(f"  Calmar Ratio:      {tm['calmar_ratio']:>10.3f}")
            print(f"  Win Rate:          {tm['win_rate']:>10.2%}")
            print(f"  Profit Factor:     {tm['profit_factor']:>10.3f}")
            print(f"  Number of Trades:  {tm['num_trades']:>10.0f}")

        # Probability Stats
        if 'probability_stats' in results:
            print("\nProbability Statistics:")
            print("-" * 70)
            ps = results['probability_stats']
            print(f"  Mean Confidence: {ps['mean_confidence']:.4f}")
            print(f"  Std Confidence:  {ps['std_confidence']:.4f}")
            print(f"  Range:           [{ps['min_confidence']:.4f}, {ps['max_confidence']:.4f}]")

        print("=" * 70 + "\n")


if __name__ == "__main__":
    # Test evaluation system
    print("Testing Evaluation System...\n")

    # Create synthetic backtest data
    np.random.seed(42)
    n_samples = 1000

    # Simulate predictions and actual returns
    y_true = np.random.randint(0, 3, size=n_samples)
    y_pred = y_true.copy()
    # Add some noise (70% accuracy)
    noise_idx = np.random.choice(n_samples, size=int(n_samples * 0.3), replace=False)
    y_pred[noise_idx] = np.random.randint(0, 3, size=len(noise_idx))

    # Simulate actual returns
    actual_returns = np.random.randn(n_samples) * 0.01  # 1% volatility

    # Simulate probabilities
    y_proba = np.random.dirichlet([5, 2, 5], size=n_samples)

    # Timestamps
    timestamps = pd.date_range('2023-01-01', periods=n_samples, freq='1H')

    print("1. Testing Trading Metrics:")
    print("-" * 70)
    tm_calculator = TradingMetrics()
    trading_metrics = tm_calculator.calculate_all_metrics(y_pred, actual_returns)
    for key, value in trading_metrics.items():
        if isinstance(value, float):
            print(f"  {key:20s}: {value:.4f}")
        else:
            print(f"  {key:20s}: {value}")

    print("\n2. Testing ML Metrics:")
    print("-" * 70)
    ml_calculator = MLMetrics()
    ml_calculator.print_report(y_true, y_pred)

    print("\n3. Testing Time Series Cross-Validation:")
    print("-" * 70)

    # Mock model for testing
    class MockModel:
        def fit(self, X, y):
            pass

        def predict(self, X):
            return np.random.randint(0, 3, size=len(X))

    X = np.random.randn(n_samples, 128)
    cv = TimeSeriesCrossValidator(n_splits=5, gap=10)
    cv_results = cv.cross_validate(MockModel(), X, y_true, returns=actual_returns)

    print("\nCross-Validation Results:")
    agg = cv_results['aggregated']
    print(f"  ML Metrics:")
    for key, value in agg['ml_metrics'].items():
        print(f"    {key:20s}: {value:.4f}")

    print("\n4. Testing Complete Backtest Evaluator:")
    print("-" * 70)
    evaluator = BacktestEvaluator()
    results = evaluator.evaluate(
        y_true, y_pred,
        y_proba=y_proba,
        actual_returns=actual_returns,
        timestamps=timestamps
    )
    evaluator.print_summary(results)

    print("✓ Evaluation System test passed!")
