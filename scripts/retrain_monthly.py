"""
Monthly Model Retraining Script.

Automated script for monthly model retraining with:
- Data collection from last N months
- Feature engineering
- Model training
- Evaluation and comparison with current model
- Model versioning (S3 + Git LFS)
- Deployment if improved

Usage:
    python scripts/retrain_monthly.py --months 12 --deploy

Can be run via:
- GitHub Actions (scheduled)
- Cron job
- Manual execution

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import argparse
import logging
from datetime import datetime, timedelta
import json
import numpy as np
import pandas as pd
import torch
import boto3
from typing import Dict, Optional

from ml.feature_engineering import FeatureEngineer, LabelGenerator, create_sequences
from ml.training import EnsembleTrainer
from ml.deep_ensemble import MLEnsemble
from ml.confidence_calibration import ConfidenceCalibrator
from ml.evaluation import BacktestEvaluator, TimeSeriesCrossValidator
from ml.monitoring import ModelMonitor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/retraining.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ModelRetrainingPipeline:
    """
    Complete model retraining pipeline.

    Handles data collection, training, evaluation, versioning, and deployment.
    """

    def __init__(self,
                 data_dir: str = "data/ohlcv",
                 models_dir: str = "models/ensemble",
                 s3_bucket: Optional[str] = None,
                 version_prefix: str = "v"):
        """
        Args:
            data_dir: Directory containing OHLCV data
            models_dir: Directory for models
            s3_bucket: S3 bucket for model storage (optional)
            version_prefix: Prefix for version strings
        """
        self.data_dir = Path(data_dir)
        self.models_dir = Path(models_dir)
        self.s3_bucket = s3_bucket
        self.version_prefix = version_prefix

        # Initialize components
        self.feature_engineer = FeatureEngineer()
        self.label_generator = LabelGenerator()

        # S3 client (if bucket provided)
        self.s3_client = None
        if s3_bucket:
            self.s3_client = boto3.client('s3')
            logger.info(f"S3 client initialized for bucket: {s3_bucket}")

        # Training metadata
        self.metadata = {}

    def collect_training_data(self,
                             symbol: str = "BTC/USDT",
                             months: int = 12,
                             timeframe: str = "15m") -> pd.DataFrame:
        """
        Collect training data from last N months.

        Args:
            symbol: Trading symbol
            months: Number of months of data to collect
            timeframe: Data timeframe

        Returns:
            DataFrame with OHLCV data
        """
        logger.info(f"Collecting {months} months of data for {symbol} {timeframe}")

        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=months * 30)

        # Load data (placeholder - replace with actual data loading)
        # In production, this would load from database, exchange API, or files
        logger.info(f"Loading data from {start_date} to {end_date}")

        # For now, generate synthetic data for testing
        # REPLACE THIS WITH ACTUAL DATA LOADING
        dates = pd.date_range(start=start_date, end=end_date, freq='15min')
        n_samples = len(dates)

        df = pd.DataFrame({
            'timestamp': dates,
            'open': 50000 + np.random.randn(n_samples).cumsum() * 100,
            'high': 0,
            'low': 0,
            'close': 0,
            'volume': np.random.uniform(100, 1000, n_samples)
        })

        # Generate OHLC from open
        df['close'] = df['open'] + np.random.randn(n_samples) * 100
        df['high'] = df[['open', 'close']].max(axis=1) + np.abs(np.random.randn(n_samples)) * 50
        df['low'] = df[['open', 'close']].min(axis=1) - np.abs(np.random.randn(n_samples)) * 50

        logger.info(f"Loaded {len(df)} samples")

        return df

    def prepare_training_data(self,
                             df: pd.DataFrame,
                             seq_len: int = 60) -> Tuple:
        """
        Engineer features and create sequences.

        Args:
            df: OHLCV dataframe
            seq_len: Sequence length

        Returns:
            Tuple of (X, y, timestamps)
        """
        logger.info("Engineering features...")
        features_df = self.feature_engineer.engineer_features(df)

        logger.info("Generating labels...")
        labels_df = self.label_generator.generate_labels(features_df)

        logger.info("Creating sequences...")
        X, y, timestamps = create_sequences(
            features_df,
            labels_df,
            seq_len=seq_len
        )

        logger.info(f"Created {len(X)} sequences with {X.shape[2]} features")

        return X, y, timestamps

    def train_new_models(self,
                        X: np.ndarray,
                        y: np.ndarray,
                        version: str) -> Dict:
        """
        Train new ensemble models.

        Args:
            X: Features
            y: Labels
            version: Version string

        Returns:
            Training results dictionary
        """
        logger.info("=" * 70)
        logger.info(f"Training new models: {version}")
        logger.info("=" * 70)

        # Initialize trainer
        trainer = EnsembleTrainer(
            input_size=X.shape[2],
            seq_len=X.shape[1],
            num_classes=3
        )

        # Prepare data loaders
        train_loader, val_loader = trainer.prepare_data(
            X, y, val_split=0.2, batch_size=256
        )

        # Train all models
        histories = trainer.train_all_models(
            train_loader, val_loader,
            save_dir=str(self.models_dir / version)
        )

        # Save training report
        trainer.save_training_report(
            str(self.models_dir / version / "training_report.json")
        )

        return histories

    def evaluate_models(self,
                       X: np.ndarray,
                       y: np.ndarray,
                       version: str,
                       test_split: float = 0.2) -> Dict:
        """
        Evaluate trained models.

        Args:
            X: Features
            y: Labels
            version: Version string
            test_split: Test set split

        Returns:
            Evaluation results
        """
        logger.info("Evaluating new models...")

        # Load trained ensemble
        ensemble = MLEnsemble(
            input_size=X.shape[2],
            seq_len=X.shape[1],
            num_classes=3
        )
        ensemble.load_ensemble(str(self.models_dir / version), version="v1.0")

        # Split test data
        n_test = int(len(X) * test_split)
        X_test = X[-n_test:]
        y_test = y[-n_test:]

        # Get predictions
        X_test_tensor = torch.from_numpy(X_test).float()
        ensemble.eval()

        predictions = []
        probabilities = []

        with torch.no_grad():
            for i in range(len(X_test)):
                result = ensemble.predict(X_test_tensor[i:i+1])
                predictions.append(['SHORT', 'NEUTRAL', 'LONG'].index(result['signal']))
                probabilities.append([
                    result['probabilities']['SHORT'],
                    result['probabilities']['NEUTRAL'],
                    result['probabilities']['LONG']
                ])

        predictions = np.array(predictions)
        probabilities = np.array(probabilities)

        # Evaluate
        evaluator = BacktestEvaluator()
        results = evaluator.evaluate(
            y_true=y_test,
            y_pred=predictions,
            y_proba=probabilities
        )

        # Print summary
        evaluator.print_summary(results)

        # Save evaluation results
        eval_path = self.models_dir / version / "evaluation_results.json"
        with open(eval_path, 'w') as f:
            # Convert numpy types
            results_json = {
                k: v.tolist() if isinstance(v, np.ndarray) else v
                for k, v in results.items()
                if k != 'equity_curve_df'
            }
            json.dump(results_json, f, indent=2)

        logger.info(f"Evaluation results saved to {eval_path}")

        return results

    def compare_with_current(self,
                            new_results: Dict,
                            current_version: str) -> Tuple[bool, Dict]:
        """
        Compare new model with current production model.

        Args:
            new_results: Evaluation results for new model
            current_version: Current production version

        Returns:
            Tuple of (should_deploy, comparison_metrics)
        """
        logger.info(f"Comparing with current version: {current_version}")

        # Load current model results
        current_results_path = self.models_dir / current_version / "evaluation_results.json"

        if not current_results_path.exists():
            logger.warning("No current model results found. Will deploy new model.")
            return True, {}

        with open(current_results_path, 'r') as f:
            current_results = json.load(f)

        # Compare key metrics
        new_acc = new_results['ml_metrics']['accuracy']
        current_acc = current_results['ml_metrics']['accuracy']

        comparison = {
            'new_accuracy': new_acc,
            'current_accuracy': current_acc,
            'accuracy_improvement': new_acc - current_acc,
            'improvement_pct': (new_acc - current_acc) / current_acc * 100
        }

        # Decision: deploy if accuracy improved by at least 1%
        should_deploy = comparison['accuracy_improvement'] > 0.01

        logger.info(f"Accuracy comparison:")
        logger.info(f"  Current: {current_acc:.4f}")
        logger.info(f"  New:     {new_acc:.4f}")
        logger.info(f"  Change:  {comparison['accuracy_improvement']:+.4f} ({comparison['improvement_pct']:+.2f}%)")
        logger.info(f"  Deploy:  {should_deploy}")

        return should_deploy, comparison

    def version_and_upload(self, version: str) -> None:
        """
        Version models and upload to S3.

        Args:
            version: Version string
        """
        logger.info(f"Versioning and uploading models: {version}")

        version_dir = self.models_dir / version

        # Upload to S3 if configured
        if self.s3_client and self.s3_bucket:
            logger.info(f"Uploading to S3 bucket: {self.s3_bucket}")

            for file_path in version_dir.glob("*.pt"):
                s3_key = f"models/{version}/{file_path.name}"
                logger.info(f"  Uploading {file_path.name} to {s3_key}")

                self.s3_client.upload_file(
                    str(file_path),
                    self.s3_bucket,
                    s3_key
                )

            # Upload metadata
            for file_path in version_dir.glob("*.json"):
                s3_key = f"models/{version}/{file_path.name}"
                logger.info(f"  Uploading {file_path.name} to {s3_key}")

                self.s3_client.upload_file(
                    str(file_path),
                    self.s3_bucket,
                    s3_key
                )

            logger.info("Upload to S3 completed")

        # TODO: Add Git LFS versioning
        # git lfs track "*.pt"
        # git add models/{version}/*.pt
        # git commit -m "Add model {version}"
        # git tag {version}
        # git push origin {version}

    def run(self,
            symbol: str = "BTC/USDT",
            months: int = 12,
            deploy: bool = False,
            current_version: str = "v1.0") -> Dict:
        """
        Run complete retraining pipeline.

        Args:
            symbol: Trading symbol
            months: Months of data to use
            deploy: Whether to deploy if improved
            current_version: Current production version

        Returns:
            Retraining results
        """
        logger.info("=" * 70)
        logger.info("MONTHLY MODEL RETRAINING PIPELINE")
        logger.info("=" * 70)

        start_time = datetime.utcnow()

        # Generate new version
        new_version = f"{self.version_prefix}{start_time.strftime('%Y%m%d')}"
        logger.info(f"New version: {new_version}")

        try:
            # Step 1: Collect data
            df = self.collect_training_data(symbol, months)

            # Step 2: Prepare data
            X, y, timestamps = self.prepare_training_data(df)

            # Step 3: Train models
            histories = self.train_new_models(X, y, new_version)

            # Step 4: Evaluate
            eval_results = self.evaluate_models(X, y, new_version)

            # Step 5: Compare with current
            should_deploy, comparison = self.compare_with_current(
                eval_results, current_version
            )

            # Step 6: Version and upload
            self.version_and_upload(new_version)

            # Step 7: Deploy if approved
            if deploy and should_deploy:
                logger.info("Deploying new model version...")
                # Create symlink to new version
                latest_link = self.models_dir / "latest"
                if latest_link.exists():
                    latest_link.unlink()
                latest_link.symlink_to(new_version)
                logger.info(f"Deployed {new_version} as latest")
            else:
                logger.info("Skipping deployment (--deploy flag required or model not improved)")

            # Create summary
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            summary = {
                'success': True,
                'version': new_version,
                'timestamp': start_time.isoformat(),
                'duration_seconds': duration,
                'data_samples': len(df),
                'training_samples': len(X),
                'eval_results': eval_results['ml_metrics'],
                'comparison': comparison,
                'deployed': deploy and should_deploy
            }

            # Save summary
            summary_path = self.models_dir / new_version / "retraining_summary.json"
            with open(summary_path, 'w') as f:
                json.dump(summary, f, indent=2, default=str)

            logger.info("=" * 70)
            logger.info("RETRAINING COMPLETED SUCCESSFULLY")
            logger.info(f"Version: {new_version}")
            logger.info(f"Duration: {duration:.1f}s")
            logger.info(f"Deployed: {deploy and should_deploy}")
            logger.info("=" * 70)

            return summary

        except Exception as e:
            logger.error(f"Retraining failed: {e}", exc_info=True)

            summary = {
                'success': False,
                'error': str(e),
                'timestamp': start_time.isoformat()
            }

            return summary


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Monthly model retraining script")

    parser.add_argument(
        '--symbol',
        type=str,
        default='BTC/USDT',
        help='Trading symbol (default: BTC/USDT)'
    )
    parser.add_argument(
        '--months',
        type=int,
        default=12,
        help='Months of training data (default: 12)'
    )
    parser.add_argument(
        '--deploy',
        action='store_true',
        help='Deploy new model if improved'
    )
    parser.add_argument(
        '--current-version',
        type=str,
        default='v1.0',
        help='Current production version (default: v1.0)'
    )
    parser.add_argument(
        '--s3-bucket',
        type=str,
        default=None,
        help='S3 bucket for model storage'
    )

    args = parser.parse_args()

    # Create logs directory
    Path('logs').mkdir(exist_ok=True)

    # Run pipeline
    pipeline = ModelRetrainingPipeline(
        s3_bucket=args.s3_bucket
    )

    results = pipeline.run(
        symbol=args.symbol,
        months=args.months,
        deploy=args.deploy,
        current_version=args.current_version
    )

    # Exit with appropriate code
    sys.exit(0 if results['success'] else 1)


if __name__ == "__main__":
    main()
