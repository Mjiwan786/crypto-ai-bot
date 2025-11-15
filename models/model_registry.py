"""
Model Registry Manager

Manages ML model versions, metadata, and promotion/rollback.

Features:
- Model versioning with timestamps
- Performance metrics tracking (PF, Sharpe, Win Rate)
- Automatic promotion based on performance
- Rollback capability
- Model metadata persistence (models/registry.json)
- Redis integration for state tracking

Author: Crypto AI Bot Team
Date: 2025-11-09
"""

import os
import sys
import time
import json
import shutil
import pickle
import logging
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
from dataclasses import dataclass, asdict

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("redis-py not available, Redis features disabled")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ModelMetadata:
    """Metadata for a trained model."""

    # Identity
    model_id: str  # e.g., "predictor_v2_20251109_120000"
    model_type: str  # e.g., "predictor_v2", "risk_model", "regime_detector"
    version: str  # e.g., "1.0.0", "2.1.3"

    # Training info
    trained_at: int  # Unix timestamp
    training_data_start: int
    training_data_end: int
    training_samples: int
    training_pairs: List[str]

    # Model file paths
    model_path: str  # e.g., "models/predictor_v2_20251109_120000.pkl"
    backup_path: Optional[str] = None

    # Performance metrics (on validation set)
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate_pct: float = 0.0
    accuracy: float = 0.0  # For classification models
    auc: float = 0.0  # Area under ROC curve

    # Feature importance (top 5)
    feature_importance: Optional[Dict[str, float]] = None

    # Status
    status: str = "trained"  # trained, validated, promoted, deprecated, failed
    is_production: bool = False

    # Validation results
    validation_results: Optional[Dict] = None

    # Notes
    notes: str = ""


@dataclass
class ModelRegistry:
    """Registry of all model versions."""

    models: List[ModelMetadata]
    production_model_id: Optional[str] = None
    baseline_model_id: Optional[str] = None
    last_updated: int = 0


# ============================================================================
# MODEL REGISTRY MANAGER
# ============================================================================

class ModelRegistryManager:
    """
    Manage ML model registry with versioning and promotion.
    """

    def __init__(
        self,
        registry_path: str = "models/registry.json",
        models_dir: str = "models",
        redis_url: Optional[str] = None,
        ssl_ca_cert: Optional[str] = None,
    ):
        self.registry_path = Path(registry_path)
        self.models_dir = Path(models_dir)

        # Create models directory if needed
        self.models_dir.mkdir(parents=True, exist_ok=True)

        # Redis connection
        self.redis_url = redis_url or os.getenv('REDIS_URL')
        self.ssl_ca_cert = ssl_ca_cert or os.getenv(
            'REDIS_SSL_CA_CERT',
            'config/certs/redis_ca.pem'
        )
        self.redis_client = None

        if REDIS_AVAILABLE and self.redis_url:
            self._connect_redis()

        # Load or initialize registry
        self.registry = self._load_registry()

        logger.info(f"ModelRegistryManager initialized: {len(self.registry.models)} models")

    def _connect_redis(self):
        """Connect to Redis."""
        try:
            if self.redis_url.startswith('rediss://'):
                self.redis_client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    ssl_ca_certs=self.ssl_ca_cert,
                )
            else:
                self.redis_client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                )

            self.redis_client.ping()
            logger.info("Connected to Redis for model registry")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None

    def _load_registry(self) -> ModelRegistry:
        """Load registry from disk."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, 'r') as f:
                    data = json.load(f)

                # Convert to dataclass
                models = [ModelMetadata(**m) for m in data.get('models', [])]
                registry = ModelRegistry(
                    models=models,
                    production_model_id=data.get('production_model_id'),
                    baseline_model_id=data.get('baseline_model_id'),
                    last_updated=data.get('last_updated', 0),
                )

                logger.info(f"Loaded registry: {len(registry.models)} models")
                return registry

            except Exception as e:
                logger.error(f"Failed to load registry: {e}")
                return ModelRegistry(models=[])
        else:
            logger.info("No existing registry, creating new one")
            return ModelRegistry(models=[])

    def _save_registry(self):
        """Save registry to disk."""
        try:
            data = {
                'models': [asdict(m) for m in self.registry.models],
                'production_model_id': self.registry.production_model_id,
                'baseline_model_id': self.registry.baseline_model_id,
                'last_updated': int(datetime.now().timestamp()),
            }

            # Write to temp file first
            temp_path = self.registry_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2)

            # Atomic replace
            temp_path.replace(self.registry_path)

            logger.info(f"Saved registry: {len(self.registry.models)} models")

            # Also publish to Redis
            if self.redis_client:
                self._publish_to_redis()

        except Exception as e:
            logger.error(f"Failed to save registry: {e}")

    def _publish_to_redis(self):
        """Publish registry state to Redis."""
        if not self.redis_client:
            return

        try:
            # Publish production model info
            if self.registry.production_model_id:
                prod_model = self.get_model(self.registry.production_model_id)
                if prod_model:
                    self.redis_client.set(
                        'models:production:metadata',
                        json.dumps(asdict(prod_model)),
                        ex=86400,  # 24 hour expiry
                    )

            # Publish registry summary
            summary = {
                'total_models': len(self.registry.models),
                'production_model_id': self.registry.production_model_id,
                'baseline_model_id': self.registry.baseline_model_id,
                'last_updated': self.registry.last_updated,
            }

            self.redis_client.set(
                'models:registry:summary',
                json.dumps(summary),
                ex=86400,
            )

            logger.debug("Published registry to Redis")

        except Exception as e:
            logger.error(f"Failed to publish to Redis: {e}")

    def register_model(
        self,
        model_path: str,
        model_type: str,
        training_info: Dict,
        performance_metrics: Dict,
        feature_importance: Optional[Dict] = None,
    ) -> ModelMetadata:
        """Register a newly trained model."""

        # Generate model ID
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        model_id = f"{model_type}_{timestamp}"

        # Create metadata
        metadata = ModelMetadata(
            model_id=model_id,
            model_type=model_type,
            version=training_info.get('version', '1.0.0'),
            trained_at=int(datetime.now().timestamp()),
            training_data_start=training_info.get('data_start', 0),
            training_data_end=training_info.get('data_end', 0),
            training_samples=training_info.get('samples', 0),
            training_pairs=training_info.get('pairs', []),
            model_path=model_path,
            profit_factor=performance_metrics.get('profit_factor', 0.0),
            sharpe_ratio=performance_metrics.get('sharpe_ratio', 0.0),
            win_rate_pct=performance_metrics.get('win_rate_pct', 0.0),
            accuracy=performance_metrics.get('accuracy', 0.0),
            auc=performance_metrics.get('auc', 0.0),
            feature_importance=feature_importance,
            status='trained',
            is_production=False,
        )

        # Add to registry
        self.registry.models.append(metadata)

        # Set as baseline if first model
        if not self.registry.baseline_model_id:
            self.registry.baseline_model_id = model_id
            metadata.status = 'baseline'
            logger.info(f"Set baseline model: {model_id}")

        # Save registry
        self._save_registry()

        logger.info(
            f"Registered model {model_id}: "
            f"PF={metadata.profit_factor:.2f}, "
            f"Sharpe={metadata.sharpe_ratio:.2f}, "
            f"WinRate={metadata.win_rate_pct:.1f}%"
        )

        return metadata

    def get_model(self, model_id: str) -> Optional[ModelMetadata]:
        """Get model metadata by ID."""
        for model in self.registry.models:
            if model.model_id == model_id:
                return model
        return None

    def get_production_model(self) -> Optional[ModelMetadata]:
        """Get current production model."""
        if self.registry.production_model_id:
            return self.get_model(self.registry.production_model_id)
        return None

    def get_baseline_model(self) -> Optional[ModelMetadata]:
        """Get baseline model."""
        if self.registry.baseline_model_id:
            return self.get_model(self.registry.baseline_model_id)
        return None

    def get_models_by_type(self, model_type: str) -> List[ModelMetadata]:
        """Get all models of a specific type."""
        return [m for m in self.registry.models if m.model_type == model_type]

    def evaluate_for_promotion(
        self,
        candidate_model_id: str,
        comparison_model_id: Optional[str] = None,
    ) -> Dict:
        """
        Evaluate if candidate model should be promoted.

        Returns:
            Dict with 'should_promote', 'reason', 'comparison'
        """

        candidate = self.get_model(candidate_model_id)
        if not candidate:
            return {
                'should_promote': False,
                'reason': 'Candidate model not found',
                'comparison': None,
            }

        # Determine comparison model (baseline or production)
        if comparison_model_id:
            baseline = self.get_model(comparison_model_id)
        else:
            baseline = self.get_production_model() or self.get_baseline_model()

        if not baseline:
            # No baseline, auto-promote first model
            return {
                'should_promote': True,
                'reason': 'No baseline model exists',
                'comparison': None,
            }

        # Compare performance
        comparison = {
            'candidate_id': candidate.model_id,
            'baseline_id': baseline.model_id,
            'profit_factor': {
                'candidate': candidate.profit_factor,
                'baseline': baseline.profit_factor,
                'delta': candidate.profit_factor - baseline.profit_factor,
                'improvement_pct': (
                    (candidate.profit_factor - baseline.profit_factor) /
                    baseline.profit_factor * 100
                ) if baseline.profit_factor > 0 else 0,
            },
            'sharpe_ratio': {
                'candidate': candidate.sharpe_ratio,
                'baseline': baseline.sharpe_ratio,
                'delta': candidate.sharpe_ratio - baseline.sharpe_ratio,
            },
            'win_rate_pct': {
                'candidate': candidate.win_rate_pct,
                'baseline': baseline.win_rate_pct,
                'delta': candidate.win_rate_pct - baseline.win_rate_pct,
            },
        }

        # Promotion criteria: PF must be better
        should_promote = candidate.profit_factor > baseline.profit_factor

        if should_promote:
            reason = (
                f"Candidate PF {candidate.profit_factor:.2f} > "
                f"Baseline PF {baseline.profit_factor:.2f} "
                f"(+{comparison['profit_factor']['improvement_pct']:.1f}%)"
            )
        else:
            reason = (
                f"Candidate PF {candidate.profit_factor:.2f} <= "
                f"Baseline PF {baseline.profit_factor:.2f}"
            )

        return {
            'should_promote': should_promote,
            'reason': reason,
            'comparison': comparison,
        }

    def promote_model(self, model_id: str, backup_current: bool = True) -> bool:
        """Promote model to production."""

        candidate = self.get_model(model_id)
        if not candidate:
            logger.error(f"Model {model_id} not found")
            return False

        # Backup current production model
        if backup_current and self.registry.production_model_id:
            current_prod = self.get_production_model()
            if current_prod:
                # Copy model file to backup
                backup_path = self.models_dir / f"{current_prod.model_id}_backup.pkl"
                try:
                    shutil.copy2(current_prod.model_path, backup_path)
                    current_prod.backup_path = str(backup_path)
                    current_prod.status = 'deprecated'
                    current_prod.is_production = False
                    logger.info(f"Backed up model {current_prod.model_id}")
                except Exception as e:
                    logger.error(f"Failed to backup model: {e}")

        # Promote candidate
        candidate.status = 'promoted'
        candidate.is_production = True
        self.registry.production_model_id = model_id

        # Save registry
        self._save_registry()

        logger.info(
            f"Promoted model {model_id} to production: "
            f"PF={candidate.profit_factor:.2f}, "
            f"Sharpe={candidate.sharpe_ratio:.2f}"
        )

        # Publish event to Redis
        if self.redis_client:
            try:
                self.redis_client.xadd(
                    'models:promotion_events',
                    {
                        'model_id': model_id,
                        'model_type': candidate.model_type,
                        'profit_factor': candidate.profit_factor,
                        'sharpe_ratio': candidate.sharpe_ratio,
                        'promoted_at': int(datetime.now().timestamp()),
                    },
                    maxlen=100,
                )
            except Exception as e:
                logger.error(f"Failed to publish promotion event: {e}")

        return True

    def rollback_to_previous(self) -> bool:
        """Rollback to previous production model."""

        if not self.registry.production_model_id:
            logger.error("No production model to rollback from")
            return False

        # Find previous production model
        deprecated_models = [
            m for m in self.registry.models
            if m.status == 'deprecated' and m.backup_path
        ]

        if not deprecated_models:
            logger.error("No previous model to rollback to")
            return False

        # Get most recent deprecated model
        previous = max(deprecated_models, key=lambda m: m.trained_at)

        # Demote current production
        current_prod = self.get_production_model()
        if current_prod:
            current_prod.status = 'failed'
            current_prod.is_production = False

        # Restore previous model
        previous.status = 'promoted'
        previous.is_production = True
        self.registry.production_model_id = previous.model_id

        # Save registry
        self._save_registry()

        logger.info(f"Rolled back to model {previous.model_id}")

        # Publish rollback event
        if self.redis_client:
            try:
                self.redis_client.xadd(
                    'models:rollback_events',
                    {
                        'model_id': previous.model_id,
                        'rolled_back_at': int(datetime.now().timestamp()),
                    },
                    maxlen=100,
                )
            except Exception as e:
                logger.error(f"Failed to publish rollback event: {e}")

        return True

    def cleanup_old_models(self, keep_last_n: int = 10):
        """Remove old model files, keeping last N."""

        # Group by model type
        by_type = {}
        for model in self.registry.models:
            if model.model_type not in by_type:
                by_type[model.model_type] = []
            by_type[model.model_type].append(model)

        # For each type, keep last N + production + baseline
        deleted_count = 0

        for model_type, models in by_type.items():
            # Sort by training time
            models.sort(key=lambda m: m.trained_at, reverse=True)

            # Identify models to keep
            keep_ids = set()

            # Always keep production and baseline
            if self.registry.production_model_id:
                keep_ids.add(self.registry.production_model_id)
            if self.registry.baseline_model_id:
                keep_ids.add(self.registry.baseline_model_id)

            # Keep last N
            for i, model in enumerate(models):
                if i < keep_last_n:
                    keep_ids.add(model.model_id)

            # Delete others
            for model in models:
                if model.model_id not in keep_ids:
                    try:
                        # Delete model file
                        if os.path.exists(model.model_path):
                            os.remove(model.model_path)
                            logger.info(f"Deleted old model file: {model.model_path}")
                            deleted_count += 1

                        # Delete backup if exists
                        if model.backup_path and os.path.exists(model.backup_path):
                            os.remove(model.backup_path)

                        # Remove from registry
                        self.registry.models.remove(model)

                    except Exception as e:
                        logger.error(f"Failed to delete model {model.model_id}: {e}")

        if deleted_count > 0:
            self._save_registry()
            logger.info(f"Cleaned up {deleted_count} old models")

    def get_registry_summary(self) -> Dict:
        """Get registry summary."""
        by_type = {}
        by_status = {}

        for model in self.registry.models:
            # Count by type
            by_type[model.model_type] = by_type.get(model.model_type, 0) + 1

            # Count by status
            by_status[model.status] = by_status.get(model.status, 0) + 1

        return {
            'total_models': len(self.registry.models),
            'by_type': by_type,
            'by_status': by_status,
            'production_model_id': self.registry.production_model_id,
            'baseline_model_id': self.registry.baseline_model_id,
            'last_updated': self.registry.last_updated,
        }


# ============================================================================
# SELF-CHECK
# ============================================================================

def self_check():
    """Self-check function."""

    print("="*80)
    print("MODEL REGISTRY MANAGER - SELF CHECK")
    print("="*80)

    # Initialize manager
    print("\n1. Initializing model registry manager...")
    manager = ModelRegistryManager(
        registry_path="models/registry_test.json",
        models_dir="models/test",
    )
    print("   [OK] Manager initialized")

    # Register a test model
    print("\n2. Registering test model...")

    # Create dummy model file
    test_model_path = "models/test/predictor_v2_test.pkl"
    os.makedirs("models/test", exist_ok=True)

    with open(test_model_path, 'wb') as f:
        pickle.dump({'dummy': 'model'}, f)

    metadata = manager.register_model(
        model_path=test_model_path,
        model_type="predictor_v2",
        training_info={
            'version': '1.0.0',
            'data_start': 1699564800,
            'data_end': 1707340800,
            'samples': 10000,
            'pairs': ['BTC/USD', 'ETH/USD'],
        },
        performance_metrics={
            'profit_factor': 1.5,
            'sharpe_ratio': 1.4,
            'win_rate_pct': 60.0,
            'accuracy': 0.65,
            'auc': 0.72,
        },
        feature_importance={
            'returns': 0.25,
            'rsi': 0.20,
            'whale_flow': 0.18,
        },
    )

    print(f"   [OK] Registered model: {metadata.model_id}")
    print(f"   [OK] PF: {metadata.profit_factor}")
    print(f"   [OK] Sharpe: {metadata.sharpe_ratio}")

    # Register another model (better performance)
    print("\n3. Registering improved model...")

    # Sleep to ensure different timestamp
    time.sleep(1)

    test_model_path_2 = "models/test/predictor_v2_test_2.pkl"
    with open(test_model_path_2, 'wb') as f:
        pickle.dump({'dummy': 'model_v2'}, f)

    metadata_2 = manager.register_model(
        model_path=test_model_path_2,
        model_type="predictor_v2",
        training_info={
            'version': '1.1.0',
            'data_start': 1699564800,
            'data_end': 1707340800,
            'samples': 12000,
            'pairs': ['BTC/USD', 'ETH/USD', 'SOL/USD'],
        },
        performance_metrics={
            'profit_factor': 1.7,  # Better than v1
            'sharpe_ratio': 1.6,
            'win_rate_pct': 62.0,
            'accuracy': 0.68,
            'auc': 0.75,
        },
    )

    print(f"   [OK] Registered model: {metadata_2.model_id}")

    # Evaluate for promotion
    print("\n4. Evaluating for promotion...")

    eval_result = manager.evaluate_for_promotion(metadata_2.model_id)

    print(f"   [OK] Should promote: {eval_result['should_promote']}")
    print(f"   [OK] Reason: {eval_result['reason']}")

    if eval_result['comparison']:
        comp = eval_result['comparison']
        print(f"   [OK] PF improvement: {comp['profit_factor']['improvement_pct']:.1f}%")

    # Promote model
    if eval_result['should_promote']:
        print("\n5. Promoting model to production...")
        success = manager.promote_model(metadata_2.model_id)

        if success:
            print(f"   [OK] Promoted {metadata_2.model_id}")
        else:
            print("   [FAIL] Promotion failed")
            return False

    # Get production model
    print("\n6. Getting production model...")
    prod_model = manager.get_production_model()

    if prod_model:
        print(f"   [OK] Production model: {prod_model.model_id}")
        print(f"   [OK] PF: {prod_model.profit_factor}")
    else:
        print("   [FAIL] No production model")
        return False

    # Get registry summary
    print("\n7. Getting registry summary...")
    summary = manager.get_registry_summary()

    print(f"   [OK] Total models: {summary['total_models']}")
    print(f"   [OK] By type: {summary['by_type']}")
    print(f"   [OK] By status: {summary['by_status']}")

    # Cleanup
    print("\n8. Cleaning up test files...")
    import shutil
    shutil.rmtree("models/test", ignore_errors=True)
    if os.path.exists("models/registry_test.json"):
        os.remove("models/registry_test.json")
    print("   [OK] Cleanup complete")

    print("\n" + "="*80)
    print("[PASS] SELF-CHECK PASSED!")
    print("="*80)
    print("\nModel Registry Manager is ready for production use.")

    return True


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    success = self_check()
    sys.exit(0 if success else 1)
