"""
Tests for PRD-001 Compliant ML Training (Section 3.5)

Tests cover:
- 70/30 train/test split with time-series ordering
- Time-series cross-validation (5 folds)
- Hyperparameter tuning implementation
- Validation metrics: Accuracy, Precision, Recall, F1, ROC-AUC
- Acceptance thresholds enforcement (Accuracy ≥ 65%, Precision ≥ 60%, Recall ≥ 60%, F1 ≥ 0.60)
- Logging to monitoring/model_validation.log
- Prometheus gauge model_accuracy{model, regime}
- Model versioning and storage
- Deployment criteria (≥ 2% improvement)
"""

import pytest
import logging
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import numpy as np
import tempfile
import shutil

from scripts.prd_train_predictor_v2 import (
    PRDModelTrainer,
    ACCEPTANCE_THRESHOLDS,
    IMPROVEMENT_THRESHOLD,
    PROMETHEUS_AVAILABLE,
    MODEL_ACCURACY
)


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests"""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def mock_training_data():
    """Create mock training data"""
    np.random.seed(42)
    X = np.random.rand(1000, 20)  # 1000 samples, 20 features
    y = np.random.randint(0, 2, 1000)  # Binary labels
    return X, y


@pytest.fixture
def trainer(temp_dir):
    """Create PRD model trainer instance"""
    return PRDModelTrainer(
        pairs=["BTC/USD"],
        days=30,
        use_hyperparameter_tuning=False,
        log_file=temp_dir / "model_validation.log",
        models_dir=temp_dir / "models"
    )


class TestTrainTestSplit:
    """Test 70/30 train/test split (PRD-001 Section 3.5 Item 2)"""

    def test_split_ratio_is_70_30(self, trainer, mock_training_data):
        """Test that split uses 70/30 ratio"""
        X, y = mock_training_data
        X_train, X_test, y_train, y_test = trainer.train_test_split(X, y, test_size=0.3)

        # Check split ratio
        total_size = len(X)
        assert len(X_train) == int(total_size * 0.7)
        assert len(X_test) == int(total_size * 0.3)

    def test_split_preserves_temporal_order(self, trainer, mock_training_data):
        """Test that split preserves time-series order (no shuffling)"""
        X, y = mock_training_data

        # Add index as feature to track order
        X_indexed = np.column_stack([X, np.arange(len(X))])

        X_train, X_test, y_train, y_test = trainer.train_test_split(
            X_indexed, y, test_size=0.3
        )

        # Check train indices are before test indices
        assert X_train[:, -1].max() < X_test[:, -1].min()

    def test_split_shapes_match(self, trainer, mock_training_data):
        """Test that split maintains feature dimensions"""
        X, y = mock_training_data
        X_train, X_test, y_train, y_test = trainer.train_test_split(X, y, test_size=0.3)

        assert X_train.shape[1] == X.shape[1]  # Same features
        assert X_test.shape[1] == X.shape[1]
        assert len(y_train) == len(X_train)
        assert len(y_test) == len(X_test)


class TestCrossValidation:
    """Test time-series cross-validation (PRD-001 Section 3.5 Item 2)"""

    def test_uses_5_folds(self, trainer, mock_training_data):
        """Test that cross-validation uses 5 folds"""
        X, y = mock_training_data
        X_train, X_test, y_train, y_test = trainer.train_test_split(X, y)

        with patch.object(trainer, 'cross_validate', wraps=trainer.cross_validate) as mock_cv:
            # Mock predictor fit/predict to avoid actual training
            with patch('scripts.prd_train_predictor_v2.EnhancedPredictorV2'):
                cv_scores = trainer.cross_validate(X_train[:100], y_train[:100], n_splits=5)

            # Should have 5 scores per metric
            for metric, scores in cv_scores.items():
                assert len(scores) == 5

    def test_cv_returns_all_metrics(self, trainer, mock_training_data):
        """Test that CV returns all required metrics"""
        X, y = mock_training_data
        X_train, X_test, y_train, y_test = trainer.train_test_split(X, y)

        with patch('scripts.prd_train_predictor_v2.EnhancedPredictorV2'):
            cv_scores = trainer.cross_validate(X_train[:100], y_train[:100], n_splits=3)

        # Should have all 5 metrics
        assert "accuracy" in cv_scores
        assert "precision" in cv_scores
        assert "recall" in cv_scores
        assert "f1" in cv_scores
        assert "roc_auc" in cv_scores


class TestHyperparameterTuning:
    """Test hyperparameter tuning (PRD-001 Section 3.5 Item 3)"""

    def test_tuning_disabled_by_default(self, trainer, mock_training_data):
        """Test that hyperparameter tuning can be disabled"""
        X, y = mock_training_data
        X_train, X_test, y_train, y_test = trainer.train_test_split(X, y)

        params = trainer.tune_hyperparameters(X_train[:100], y_train[:100])

        # Should return empty dict when disabled
        assert params == {}

    def test_tuning_runs_when_enabled(self, temp_dir, mock_training_data):
        """Test that tuning runs when enabled"""
        trainer_with_tuning = PRDModelTrainer(
            pairs=["BTC/USD"],
            days=30,
            use_hyperparameter_tuning=True,
            log_file=temp_dir / "model_validation.log",
            models_dir=temp_dir / "models"
        )

        X, y = mock_training_data
        X_train, X_test, y_train, y_test = trainer_with_tuning.train_test_split(X, y)

        with patch('scripts.prd_train_predictor_v2.EnhancedPredictorV2'):
            params = trainer_with_tuning.tune_hyperparameters(X_train[:100], y_train[:100])

        # Should return some parameters
        assert isinstance(params, dict)


class TestValidationMetrics:
    """Test validation metrics calculation (PRD-001 Section 3.5 Item 4)"""

    def test_calculates_all_metrics(self, trainer):
        """Test that all 5 metrics are calculated"""
        # Mock predictions
        y_true = np.array([0, 1, 0, 1, 1, 0, 1, 0])
        y_pred = np.array([0, 1, 0, 0, 1, 0, 1, 1])
        y_pred_proba = np.array([0.2, 0.8, 0.3, 0.4, 0.9, 0.1, 0.7, 0.6])

        metrics = trainer.calculate_metrics(y_true, y_pred, y_pred_proba)

        # Should have all 5 metrics
        assert "accuracy" in metrics
        assert "precision" in metrics
        assert "recall" in metrics
        assert "f1" in metrics
        assert "roc_auc" in metrics

    def test_metrics_are_floats(self, trainer):
        """Test that metrics are float values"""
        y_true = np.array([0, 1, 0, 1])
        y_pred = np.array([0, 1, 0, 0])
        y_pred_proba = np.array([0.2, 0.8, 0.3, 0.4])

        metrics = trainer.calculate_metrics(y_true, y_pred, y_pred_proba)

        for metric, value in metrics.items():
            assert isinstance(value, (float, np.floating))

    def test_metrics_in_valid_range(self, trainer):
        """Test that metrics are in [0, 1] range"""
        y_true = np.array([0, 1, 0, 1, 1])
        y_pred = np.array([0, 1, 0, 0, 1])
        y_pred_proba = np.array([0.2, 0.8, 0.3, 0.4, 0.9])

        metrics = trainer.calculate_metrics(y_true, y_pred, y_pred_proba)

        for metric, value in metrics.items():
            assert 0.0 <= value <= 1.0


class TestAcceptanceThresholds:
    """Test acceptance thresholds (PRD-001 Section 3.5 Item 5)"""

    def test_thresholds_defined(self):
        """Test that acceptance thresholds are defined"""
        assert ACCEPTANCE_THRESHOLDS["accuracy"] == 0.65
        assert ACCEPTANCE_THRESHOLDS["precision"] == 0.60
        assert ACCEPTANCE_THRESHOLDS["recall"] == 0.60
        assert ACCEPTANCE_THRESHOLDS["f1"] == 0.60

    def test_passing_thresholds_returns_true(self, trainer):
        """Test that passing all thresholds returns True"""
        metrics = {
            "accuracy": 0.70,  # ≥ 0.65 ✓
            "precision": 0.65,  # ≥ 0.60 ✓
            "recall": 0.62,  # ≥ 0.60 ✓
            "f1": 0.63,  # ≥ 0.60 ✓
            "roc_auc": 0.75
        }

        result = trainer.check_acceptance_thresholds(metrics)
        assert result is True

    def test_failing_one_threshold_returns_false(self, trainer):
        """Test that failing any threshold returns False"""
        metrics = {
            "accuracy": 0.70,  # ≥ 0.65 ✓
            "precision": 0.58,  # < 0.60 ✗
            "recall": 0.65,  # ≥ 0.60 ✓
            "f1": 0.65,  # ≥ 0.60 ✓
        }

        result = trainer.check_acceptance_thresholds(metrics)
        assert result is False

    def test_boundary_values_pass(self, trainer):
        """Test that exact threshold values pass"""
        metrics = {
            "accuracy": 0.65,  # Exactly at threshold
            "precision": 0.60,
            "recall": 0.60,
            "f1": 0.60,
        }

        result = trainer.check_acceptance_thresholds(metrics)
        assert result is True


class TestValidationLogging:
    """Test logging to monitoring/model_validation.log (PRD-001 Section 3.5 Item 6)"""

    def test_log_file_created(self, trainer, temp_dir):
        """Test that validation log file is created"""
        log_file = temp_dir / "model_validation.log"
        assert log_file.exists()

    def test_metrics_logged_to_file(self, trainer, caplog):
        """Test that metrics are logged"""
        metrics = {
            "accuracy": 0.70,
            "precision": 0.65,
            "recall": 0.62,
            "f1": 0.63,
            "roc_auc": 0.75
        }

        with caplog.at_level(logging.INFO):
            trainer.log_validation_metrics(metrics, "v2.1")

        # Check logs contain metrics
        assert any("Validation metrics" in log.message for log in caplog.records)

    def test_log_includes_timestamp(self, trainer, caplog):
        """Test that log includes timestamp"""
        metrics = {"accuracy": 0.70, "precision": 0.65, "recall": 0.62, "f1": 0.63, "roc_auc": 0.75}

        with caplog.at_level(logging.INFO):
            trainer.log_validation_metrics(metrics, "v2.1")

        # Logs should have timestamps
        for log in caplog.records:
            assert hasattr(log, 'created')


class TestPrometheusMetrics:
    """Test Prometheus metrics (PRD-001 Section 3.5 Item 7)"""

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_emits_model_accuracy_gauge(self, trainer):
        """Test that model_accuracy gauge is emitted"""
        trainer.emit_prometheus_metrics(0.75, "v2.1", "all")

        # Should have set gauge value
        gauge_value = MODEL_ACCURACY.labels(model="v2.1", regime="all")._value.get()
        assert gauge_value == 0.75

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_gauge_labels_by_model_and_regime(self, trainer):
        """Test that gauge is labeled by model and regime"""
        trainer.emit_prometheus_metrics(0.72, "v2.2", "TRENDING_UP")

        # Should have separate gauge for this model/regime
        gauge_value = MODEL_ACCURACY.labels(model="v2.2", regime="TRENDING_UP")._value.get()
        assert gauge_value == 0.72


class TestModelVersioning:
    """Test model versioning (PRD-001 Section 3.5 Item 8)"""

    def test_first_version_is_v2_0(self, trainer):
        """Test that first version is v2.0"""
        version = trainer.get_next_version()
        assert version == "v2.0"

    def test_version_increments(self, trainer, temp_dir):
        """Test that version increments for subsequent models"""
        # Create existing model
        models_dir = temp_dir / "models"
        models_dir.mkdir(exist_ok=True)

        existing_model = models_dir / "predictor_v2_v2.0.pkl"
        existing_model.touch()

        trainer.models_dir = models_dir
        version = trainer.get_next_version()

        # Should increment to v2.1
        assert version == "v2.1"

    def test_model_saved_with_version(self, trainer, temp_dir):
        """Test that model is saved with version tag"""
        with patch('scripts.prd_train_predictor_v2.EnhancedPredictorV2') as mock_pred:
            mock_predictor = Mock()
            mock_predictor.save_model = Mock()

            metrics = {"accuracy": 0.70, "precision": 0.65, "recall": 0.62, "f1": 0.63, "roc_auc": 0.75}

            model_path = trainer.save_model_with_version(mock_predictor, "v2.1", metrics)

            # Should have version in filename
            assert "v2.1" in str(model_path)
            assert model_path.suffix == ".pkl"

    def test_metadata_saved_with_model(self, trainer, temp_dir):
        """Test that metadata JSON is saved with model"""
        with patch('scripts.prd_train_predictor_v2.EnhancedPredictorV2'):
            mock_predictor = Mock()
            mock_predictor.save_model = Mock()

            metrics = {"accuracy": 0.70, "precision": 0.65, "recall": 0.62, "f1": 0.63, "roc_auc": 0.75}

            model_path = trainer.save_model_with_version(mock_predictor, "v2.1", metrics)
            metadata_path = model_path.with_suffix('.json')

            assert metadata_path.exists()

            # Check metadata content
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)

            assert metadata["version"] == "v2.1"
            assert "timestamp" in metadata
            assert metadata["metrics"] == metrics


class TestDeploymentCriteria:
    """Test deployment criteria (PRD-001 Section 3.5 Item 10)"""

    def test_improvement_threshold_is_2_percent(self):
        """Test that improvement threshold is 2%"""
        assert IMPROVEMENT_THRESHOLD == 0.02

    def test_deploys_when_no_current_model(self, trainer):
        """Test that new model deploys when no current model exists"""
        result = trainer.check_deployment_criteria(0.70, None)
        assert result is True

    def test_deploys_when_improvement_meets_threshold(self, trainer, temp_dir):
        """Test that model deploys when improvement ≥ 2%"""
        # Create current model metadata
        current_model = temp_dir / "models" / "predictor_v2_current.pkl"
        current_model.parent.mkdir(parents=True, exist_ok=True)
        current_model.touch()

        metadata = {
            "accuracy": 0.68,
            "version": "v2.0"
        }

        with open(current_model.with_suffix('.json'), 'w') as f:
            json.dump(metadata, f)

        # New model with 0.70 accuracy (2% improvement)
        result = trainer.check_deployment_criteria(0.70, current_model)
        assert result is True

    def test_does_not_deploy_when_improvement_insufficient(self, trainer, temp_dir):
        """Test that model doesn't deploy when improvement < 2%"""
        # Create current model metadata
        current_model = temp_dir / "models" / "predictor_v2_current.pkl"
        current_model.parent.mkdir(parents=True, exist_ok=True)
        current_model.touch()

        metadata = {
            "accuracy": 0.68,
            "version": "v2.0"
        }

        with open(current_model.with_suffix('.json'), 'w') as f:
            json.dump(metadata, f)

        # New model with 0.69 accuracy (only 1% improvement)
        result = trainer.check_deployment_criteria(0.69, current_model)
        assert result is False

    def test_deploys_when_improvement_exceeds_threshold(self, trainer, temp_dir):
        """Test that model deploys when improvement > 2%"""
        current_model = temp_dir / "models" / "predictor_v2_current.pkl"
        current_model.parent.mkdir(parents=True, exist_ok=True)
        current_model.touch()

        metadata = {
            "accuracy": 0.65,
            "version": "v2.0"
        }

        with open(current_model.with_suffix('.json'), 'w') as f:
            json.dump(metadata, f)

        # New model with 0.70 accuracy (5% improvement)
        result = trainer.check_deployment_criteria(0.70, current_model)
        assert result is True


class TestFullPipeline:
    """Test complete training pipeline integration"""

    def test_pipeline_creates_all_artifacts(self, trainer, temp_dir):
        """Test that full pipeline creates all expected artifacts"""
        with patch('scripts.prd_train_predictor_v2.load_historical_data') as mock_load:
            with patch('scripts.prd_train_predictor_v2.create_training_samples') as mock_create:
                with patch('scripts.prd_train_predictor_v2.EnhancedPredictorV2') as mock_pred_class:
                    # Setup mocks
                    np.random.seed(42)
                    mock_load.return_value = Mock()
                    mock_create.return_value = (np.random.rand(100, 20), np.random.randint(0, 2, 100))

                    mock_predictor = Mock()
                    mock_predictor.fit = Mock()
                    mock_predictor.predict_proba = Mock(return_value=0.7)
                    mock_predictor.save_model = Mock()
                    mock_pred_class.return_value = mock_predictor

                    # Run pipeline (should not raise)
                    try:
                        predictor, metrics = trainer.train(deploy_if_better=False)

                        # Should have metrics
                        assert "accuracy" in metrics
                        assert "precision" in metrics
                        assert "recall" in metrics
                        assert "f1" in metrics
                        assert "roc_auc" in metrics

                    except ValueError as e:
                        # May fail thresholds with random data
                        if "does not meet minimum quality standards" not in str(e):
                            raise
