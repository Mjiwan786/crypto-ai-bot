"""
Nightly ML Model Retraining Script

Automatically retrains ML models on latest 90-day data and promotes if performance
improves over baseline.

Features:
- Fetches last 90 days of historical data from Redis/Kraken
- Retrains enhanced predictor (predictor_v2)
- Evaluates on holdout validation set
- Compares against baseline/production model
- Promotes only if PF > baseline
- Updates model registry
- Publishes metrics to Redis

Usage:
    python scripts/nightly_retrain.py [--dry-run] [--force-promote]

Author: Crypto AI Bot Team
Date: 2025-11-09
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import numpy as np
import pandas as pd

from models.model_registry import ModelRegistryManager
from ml.predictor_v2 import EnhancedPredictorV2
from scripts.train_predictor_v2 import create_training_samples

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


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

class RetrainConfig:
    """Retraining configuration."""

    # Data parameters
    TRAINING_DAYS = 90
    VALIDATION_SPLIT = 0.2  # Last 20% for validation
    PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD"]

    # Model parameters
    MODEL_TYPE = "predictor_v2"
    MODEL_VERSION = "2.0.0"

    # Performance thresholds
    MIN_PROFIT_FACTOR = 1.2  # Minimum acceptable PF
    MIN_SAMPLES = 1000  # Minimum training samples

    # Paths
    MODELS_DIR = "models"
    REGISTRY_PATH = "models/registry.json"

    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818')
    REDIS_SSL_CA_CERT = os.getenv('REDIS_SSL_CA_CERT', 'config/certs/redis_ca.pem')


# ============================================================================
# DATA FETCHER
# ============================================================================

class DataFetcher:
    """Fetch historical data for training."""

    def __init__(self, redis_url: Optional[str] = None, ssl_ca_cert: Optional[str] = None):
        self.redis_url = redis_url or RetrainConfig.REDIS_URL
        self.ssl_ca_cert = ssl_ca_cert or RetrainConfig.REDIS_SSL_CA_CERT
        self.redis_client = None

        if REDIS_AVAILABLE:
            self._connect_redis()

    def _connect_redis(self):
        """Connect to Redis."""
        try:
            if self.redis_url.startswith('rediss://'):
                self.redis_client = redis.from_url(
                    self.redis_url,
                    decode_responses=False,  # Binary mode for pickle
                    ssl_ca_certs=self.ssl_ca_cert,
                )
            else:
                self.redis_client = redis.from_url(
                    self.redis_url,
                    decode_responses=False,
                )

            self.redis_client.ping()
            logger.info("Connected to Redis for data fetching")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None

    def fetch_historical_data(
        self,
        pair: str,
        days: int,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch historical OHLCV data for a pair.

        Returns DataFrame with columns: timestamp, open, high, low, close, volume
        """

        # Try to fetch from Redis first
        if self.redis_client:
            data = self._fetch_from_redis(pair, days)
            if data is not None:
                return data

        # Fallback: fetch from Kraken API
        logger.info(f"Fetching {pair} data from Kraken API...")
        return self._fetch_from_kraken(pair, days)

    def _fetch_from_redis(self, pair: str, days: int) -> Optional[pd.DataFrame]:
        """Fetch from Redis cache."""
        try:
            # Redis key format: ohlcv:{pair}:1m
            redis_key = f"ohlcv:{pair.replace('/', '_')}:1m"

            # Get last N entries from stream
            end_timestamp = int(time.time())
            start_timestamp = end_timestamp - (days * 86400)

            # Read from stream
            entries = self.redis_client.xrevrange(
                redis_key,
                max=f"{end_timestamp * 1000}",
                min=f"{start_timestamp * 1000}",
                count=days * 1440,  # days * minutes_per_day
            )

            if not entries:
                logger.warning(f"No data in Redis for {pair}")
                return None

            # Parse entries
            rows = []
            for entry_id, data in entries:
                rows.append({
                    'timestamp': int(data[b'timestamp']),
                    'open': float(data[b'open']),
                    'high': float(data[b'high']),
                    'low': float(data[b'low']),
                    'close': float(data[b'close']),
                    'volume': float(data[b'volume']),
                })

            df = pd.DataFrame(rows)
            df = df.sort_values('timestamp').reset_index(drop=True)

            logger.info(f"Fetched {len(df)} bars from Redis for {pair}")
            return df

        except Exception as e:
            logger.error(f"Failed to fetch from Redis: {e}")
            return None

    def _fetch_from_kraken(self, pair: str, days: int) -> Optional[pd.DataFrame]:
        """Fetch from Kraken API."""
        try:
            import ccxt

            exchange = ccxt.kraken()

            # Fetch OHLCV
            since = int((time.time() - (days * 86400)) * 1000)
            ohlcv = exchange.fetch_ohlcv(
                pair,
                timeframe='1m',
                since=since,
                limit=days * 1440,
            )

            # Convert to DataFrame
            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )

            df['timestamp'] = df['timestamp'] // 1000  # ms to seconds

            logger.info(f"Fetched {len(df)} bars from Kraken for {pair}")
            return df

        except Exception as e:
            logger.error(f"Failed to fetch from Kraken: {e}")
            return None


# ============================================================================
# MODEL TRAINER
# ============================================================================

class ModelTrainer:
    """Train and evaluate ML models."""

    def __init__(self):
        self.data_fetcher = DataFetcher()
        self.registry_manager = ModelRegistryManager(
            registry_path=RetrainConfig.REGISTRY_PATH,
            models_dir=RetrainConfig.MODELS_DIR,
            redis_url=RetrainConfig.REDIS_URL,
            ssl_ca_cert=RetrainConfig.REDIS_SSL_CA_CERT,
        )

    def run_nightly_retrain(
        self,
        dry_run: bool = False,
        force_promote: bool = False,
    ) -> Dict:
        """
        Run nightly retraining workflow.

        Returns:
            Dict with results
        """

        logger.info("="*80)
        logger.info("NIGHTLY MODEL RETRAINING - START")
        logger.info("="*80)
        logger.info(f"Dry run: {dry_run}")
        logger.info(f"Force promote: {force_promote}")

        results = {
            'started_at': int(time.time()),
            'success': False,
            'model_trained': False,
            'model_promoted': False,
            'model_id': None,
            'metrics': None,
            'comparison': None,
            'error': None,
        }

        try:
            # Step 1: Fetch training data
            logger.info("\nStep 1: Fetching training data (90 days)...")

            all_data = {}
            for pair in RetrainConfig.PAIRS:
                df = self.data_fetcher.fetch_historical_data(
                    pair,
                    days=RetrainConfig.TRAINING_DAYS,
                )

                if df is None or len(df) < 1000:
                    logger.warning(f"Insufficient data for {pair}, skipping")
                    continue

                all_data[pair] = df

            if not all_data:
                raise Exception("Failed to fetch any training data")

            total_bars = sum(len(df) for df in all_data.values())
            logger.info(f"   [OK] Fetched {total_bars} total bars for {len(all_data)} pairs")

            # Step 2: Create training samples
            logger.info("\nStep 2: Creating training samples...")

            X_train_list = []
            y_train_list = []
            X_val_list = []
            y_val_list = []

            for pair, df in all_data.items():
                # Split into train/val
                split_idx = int(len(df) * (1 - RetrainConfig.VALIDATION_SPLIT))

                train_df = df.iloc[:split_idx]
                val_df = df.iloc[split_idx:]

                # Create samples
                X_train, y_train = create_training_samples(train_df, pair, sample_every=10)
                X_val, y_val = create_training_samples(val_df, pair, sample_every=5)

                X_train_list.append(X_train)
                y_train_list.append(y_train)
                X_val_list.append(X_val)
                y_val_list.append(y_val)

            # Concatenate
            X_train = np.vstack(X_train_list)
            y_train = np.concatenate(y_train_list)
            X_val = np.vstack(X_val_list)
            y_val = np.concatenate(y_val_list)

            logger.info(f"   [OK] Training samples: {len(X_train)}")
            logger.info(f"   [OK] Validation samples: {len(X_val)}")

            if len(X_train) < RetrainConfig.MIN_SAMPLES:
                raise Exception(f"Insufficient training samples: {len(X_train)} < {RetrainConfig.MIN_SAMPLES}")

            # Step 3: Train model
            logger.info("\nStep 3: Training enhanced predictor...")

            predictor = EnhancedPredictorV2(use_lightgbm=True)

            predictor.fit(X_train, y_train)

            logger.info("   [OK] Model trained")

            # Step 4: Evaluate on validation set
            logger.info("\nStep 4: Evaluating on validation set...")

            metrics = self._evaluate_model(predictor, X_val, y_val)

            logger.info(f"   [OK] Profit Factor: {metrics['profit_factor']:.2f}")
            logger.info(f"   [OK] Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
            logger.info(f"   [OK] Win Rate: {metrics['win_rate_pct']:.1f}%")
            logger.info(f"   [OK] Accuracy: {metrics['accuracy']:.2%}")

            results['metrics'] = metrics

            # Check minimum threshold
            if metrics['profit_factor'] < RetrainConfig.MIN_PROFIT_FACTOR:
                logger.warning(
                    f"Model PF {metrics['profit_factor']:.2f} below threshold "
                    f"{RetrainConfig.MIN_PROFIT_FACTOR}"
                )

            # Step 5: Save model
            logger.info("\nStep 5: Saving model...")

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            model_filename = f"predictor_v2_{timestamp}.pkl"
            model_path = Path(RetrainConfig.MODELS_DIR) / model_filename

            if not dry_run:
                predictor.save(str(model_path))
                logger.info(f"   [OK] Model saved: {model_path}")
            else:
                logger.info(f"   [DRY RUN] Would save to: {model_path}")

            # Step 6: Register model
            logger.info("\nStep 6: Registering model in registry...")

            training_info = {
                'version': RetrainConfig.MODEL_VERSION,
                'data_start': int(time.time()) - (RetrainConfig.TRAINING_DAYS * 86400),
                'data_end': int(time.time()),
                'samples': len(X_train),
                'pairs': list(all_data.keys()),
            }

            feature_importance = None
            if hasattr(predictor, 'model_') and hasattr(predictor.model_, 'feature_importances_'):
                importance = predictor.model_.feature_importances_
                feature_names = predictor.feature_names_
                feature_importance = dict(zip(
                    feature_names[:5],
                    importance[:5].tolist()
                ))

            if not dry_run:
                metadata = self.registry_manager.register_model(
                    model_path=str(model_path),
                    model_type=RetrainConfig.MODEL_TYPE,
                    training_info=training_info,
                    performance_metrics=metrics,
                    feature_importance=feature_importance,
                )

                results['model_id'] = metadata.model_id
                results['model_trained'] = True

                logger.info(f"   [OK] Registered model: {metadata.model_id}")
            else:
                logger.info(f"   [DRY RUN] Would register model")

            # Step 7: Evaluate for promotion
            logger.info("\nStep 7: Evaluating for promotion...")

            if not dry_run:
                eval_result = self.registry_manager.evaluate_for_promotion(metadata.model_id)

                results['comparison'] = eval_result['comparison']

                logger.info(f"   [OK] Should promote: {eval_result['should_promote']}")
                logger.info(f"   [OK] Reason: {eval_result['reason']}")

                # Step 8: Promote if better (or force)
                if eval_result['should_promote'] or force_promote:
                    logger.info("\nStep 8: Promoting model to production...")

                    success = self.registry_manager.promote_model(metadata.model_id)

                    if success:
                        results['model_promoted'] = True
                        logger.info(f"   [OK] Promoted {metadata.model_id}")
                    else:
                        logger.error("   [FAIL] Promotion failed")
                else:
                    logger.info("\nStep 8: Model not promoted (performance not better than baseline)")
            else:
                logger.info("   [DRY RUN] Would evaluate for promotion")

            # Success
            results['success'] = True

        except Exception as e:
            logger.error(f"Nightly retrain failed: {e}", exc_info=True)
            results['error'] = str(e)

        finally:
            results['completed_at'] = int(time.time())
            duration = results['completed_at'] - results['started_at']

            logger.info("\n" + "="*80)
            logger.info("NIGHTLY MODEL RETRAINING - COMPLETE")
            logger.info("="*80)
            logger.info(f"Duration: {duration}s")
            logger.info(f"Success: {results['success']}")
            logger.info(f"Model trained: {results['model_trained']}")
            logger.info(f"Model promoted: {results['model_promoted']}")

        return results

    def _evaluate_model(
        self,
        predictor: EnhancedPredictorV2,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> Dict:
        """Evaluate model on validation set."""

        # Predict
        y_pred = predictor.predict(X_val)

        # Accuracy
        y_pred_binary = (y_pred >= 0.55).astype(int)
        accuracy = np.mean(y_pred_binary == y_val)

        # Simulate trading to get PF and Sharpe
        wins = []
        losses = []
        equity = [10000.0]  # Start with $10k

        for i in range(len(y_val)):
            # Skip if low confidence
            if y_pred[i] < 0.55:
                continue

            # Simulate trade
            is_winner = (y_val[i] == 1)

            if is_winner:
                pnl = 100.0  # Assume $100 win
                wins.append(pnl)
            else:
                pnl = -80.0  # Assume $80 loss
                losses.append(abs(pnl))

            equity.append(equity[-1] + pnl)

        # Calculate metrics
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = sum(losses) if losses else 1.0

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        win_rate_pct = (len(wins) / (len(wins) + len(losses)) * 100) if (wins or losses) else 0.0

        # Sharpe ratio
        if len(equity) > 1:
            returns = np.diff(equity) / equity[:-1]
            sharpe_ratio = (np.mean(returns) / np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        # AUC (for binary classification)
        try:
            from sklearn.metrics import roc_auc_score
            auc = roc_auc_score(y_val, y_pred)
        except:
            auc = 0.0

        return {
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe_ratio,
            'win_rate_pct': win_rate_pct,
            'accuracy': accuracy,
            'auc': auc,
            'total_trades': len(wins) + len(losses),
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
        }


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main execution."""

    parser = argparse.ArgumentParser(description='Nightly ML model retraining')

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run mode (no model saving/promotion)'
    )

    parser.add_argument(
        '--force-promote',
        action='store_true',
        help='Force promote even if performance not better'
    )

    args = parser.parse_args()

    # Run retraining
    trainer = ModelTrainer()
    results = trainer.run_nightly_retrain(
        dry_run=args.dry_run,
        force_promote=args.force_promote,
    )

    # Exit code
    sys.exit(0 if results['success'] else 1)


if __name__ == '__main__':
    main()
