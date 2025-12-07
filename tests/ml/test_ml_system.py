"""
Comprehensive Unit Tests for ML System.

Tests all major components of the ML ensemble system including:
- Feature engineering
- Model architectures
- Ensemble predictions
- Confidence calibration
- Evaluation metrics
- Monitoring and drift detection

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import numpy as np
import pandas as pd
import torch
import tempfile
import shutil
from datetime import datetime

from ml.feature_engineering import FeatureEngineer, LabelGenerator, create_sequences
from ml.models.lstm_model import LSTMModel
from ml.models.transformer_model import TransformerModel
from ml.models.cnn_model import CNNModel
from ml.deep_ensemble import MLEnsemble, RegimeDetector, EnsembleWeighter, MarketRegime
from ml.confidence_calibration import ConfidenceCalibrator, TemperatureScaling
from ml.evaluation import TradingMetrics, MLMetrics, TimeSeriesCrossValidator
from ml.monitoring import PerformanceTracker, DriftDetector, ModelMonitor


class TestFeatureEngineering:
    """Test feature engineering pipeline."""

    @pytest.fixture
    def sample_data(self):
        """Create sample OHLCV data."""
        dates = pd.date_range('2024-01-01', periods=500, freq='15min')
        return pd.DataFrame({
            'timestamp': dates,
            'open': 50000 + np.random.randn(500).cumsum() * 100,
            'high': 0,
            'low': 0,
            'close': 0,
            'volume': np.random.uniform(100, 1000, 500)
        })

    def test_feature_engineer_initialization(self):
        """Test FeatureEngineer initialization."""
        engineer = FeatureEngineer()
        assert engineer.feature_names is None
        assert engineer.n_features is None

    def test_feature_engineering_pipeline(self, sample_data):
        """Test complete feature engineering."""
        # Fill OHLC data
        df = sample_data.copy()
        df['close'] = df['open'] + np.random.randn(len(df)) * 100
        df['high'] = df[['open', 'close']].max(axis=1) + np.abs(np.random.randn(len(df))) * 50
        df['low'] = df[['open', 'close']].min(axis=1) - np.abs(np.random.randn(len(df))) * 50

        engineer = FeatureEngineer()
        features_df = engineer.engineer_features(df)

        # Check output
        assert len(features_df) > 0
        assert engineer.n_features > 100  # Should have 128+ features
        assert 'close' in features_df.columns
        assert 'rsi_14' in features_df.columns

    def test_label_generation(self, sample_data):
        """Test label generation."""
        df = sample_data.copy()
        df['close'] = df['open'] + np.random.randn(len(df)) * 100

        label_gen = LabelGenerator(forward_periods=4)
        labels_df = label_gen.generate_labels(df)

        # Check labels
        assert 'label' in labels_df.columns
        assert 'forward_return' in labels_df.columns
        assert labels_df['label'].isin([0, 1, 2]).all()

    def test_sequence_creation(self, sample_data):
        """Test sequence creation."""
        df = sample_data.copy()
        df['close'] = df['open']
        df['feature1'] = np.random.randn(len(df))
        df['feature2'] = np.random.randn(len(df))

        engineer = FeatureEngineer()
        features_df = engineer.engineer_features(df)

        label_gen = LabelGenerator()
        labels_df = label_gen.generate_labels(features_df)

        X, y, timestamps = create_sequences(features_df, labels_df, seq_len=60)

        # Check shapes
        assert X.shape[1] == 60  # seq_len
        assert X.shape[2] == engineer.n_features
        assert len(X) == len(y)
        assert len(X) == len(timestamps)


class TestModelArchitectures:
    """Test individual model architectures."""

    @pytest.fixture
    def sample_input(self):
        """Create sample input tensor."""
        batch_size = 8
        seq_len = 60
        features = 128
        return torch.randn(batch_size, seq_len, features)

    def test_lstm_model(self, sample_input):
        """Test LSTM model."""
        model = LSTMModel(input_size=128, hidden_size=256, num_layers=3)

        logits, attn_weights = model(sample_input)

        assert logits.shape == (8, 3)  # (batch, num_classes)
        assert attn_weights is not None

        # Test prediction
        probs = model.predict_proba(sample_input)
        assert probs.shape == (8, 3)
        assert torch.all((probs >= 0) & (probs <= 1))
        assert torch.allclose(probs.sum(dim=1), torch.ones(8), atol=1e-5)

    def test_transformer_model(self, sample_input):
        """Test Transformer model."""
        model = TransformerModel(
            input_size=128,
            d_model=512,
            nhead=8,
            num_encoder_layers=6
        )

        logits = model(sample_input)

        assert logits.shape == (8, 3)

        # Test prediction
        probs = model.predict_proba(sample_input)
        assert probs.shape == (8, 3)
        assert torch.all((probs >= 0) & (probs <= 1))

    def test_cnn_model(self, sample_input):
        """Test CNN model."""
        model = CNNModel(input_size=128, seq_len=60, num_classes=3)

        logits = model(sample_input)

        assert logits.shape == (8, 3)

        # Test prediction
        probs = model.predict_proba(sample_input)
        assert probs.shape == (8, 3)


class TestEnsemble:
    """Test ensemble system."""

    @pytest.fixture
    def sample_features_df(self):
        """Create sample features dataframe."""
        return pd.DataFrame({
            'close': np.random.randn(100) * 100 + 50000,
            'adx_14': np.random.randn(100) * 10 + 30,
            'atr_14': np.random.randn(100) * 50 + 200,
            'volatility_percentile_30': np.random.rand(100)
        })

    def test_regime_detector(self, sample_features_df):
        """Test regime detection."""
        detector = RegimeDetector()
        regime = detector.detect_regime(sample_features_df)

        assert isinstance(regime, MarketRegime)
        assert regime in [
            MarketRegime.TRENDING_UP,
            MarketRegime.TRENDING_DOWN,
            MarketRegime.RANGING,
            MarketRegime.VOLATILE,
            MarketRegime.UNKNOWN
        ]

    def test_ensemble_weighter(self):
        """Test ensemble weighting."""
        weighter = EnsembleWeighter()

        # Test base weights
        weights = weighter.get_weights(MarketRegime.UNKNOWN)
        assert 'lstm' in weights
        assert 'transformer' in weights
        assert 'cnn' in weights
        assert abs(sum(weights.values()) - 1.0) < 1e-6

        # Test regime-specific weights
        for regime in [MarketRegime.TRENDING_UP, MarketRegime.RANGING, MarketRegime.VOLATILE]:
            weights = weighter.get_weights(regime)
            assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_ensemble_prediction(self):
        """Test ensemble prediction."""
        ensemble = MLEnsemble(input_size=128, seq_len=60, num_classes=3)

        # Create sample input
        x = torch.randn(1, 60, 128)

        # Predict
        result = ensemble.predict(x)

        # Check result structure
        assert 'signal' in result
        assert result['signal'] in ['SHORT', 'NEUTRAL', 'LONG']
        assert 'probabilities' in result
        assert 'confidence' in result
        assert 'regime' in result
        assert 'weights' in result
        assert 'individual_predictions' in result

        # Check probabilities sum to 1
        prob_sum = sum(result['probabilities'].values())
        assert abs(prob_sum - 1.0) < 1e-5

    def test_ensemble_save_load(self):
        """Test ensemble save/load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ensemble = MLEnsemble(input_size=128, seq_len=60, num_classes=3)

            # Save
            ensemble.save_ensemble(tmpdir, version="test")

            # Load
            new_ensemble = MLEnsemble(input_size=128, seq_len=60, num_classes=3)
            new_ensemble.load_ensemble(tmpdir, version="test")

            # Test prediction works
            x = torch.randn(1, 60, 128)
            result = new_ensemble.predict(x)
            assert 'signal' in result


class TestConfidenceCalibration:
    """Test confidence calibration."""

    @pytest.fixture
    def sample_predictions(self):
        """Create sample predictions and labels."""
        n_samples = 500
        logits = torch.randn(n_samples, 3) * 2.0
        probs = torch.softmax(logits, dim=1).numpy()
        labels = np.random.randint(0, 3, size=n_samples)
        return probs, labels, logits

    def test_temperature_scaling(self, sample_predictions):
        """Test temperature scaling calibration."""
        probs, labels, logits = sample_predictions

        calibrator = ConfidenceCalibrator(
            num_classes=3,
            calibration_method='temperature'
        )

        # Fit
        calibrator.fit(probs, labels, logits=logits)

        # Calibrate
        calibrated_probs = calibrator.calibrate(logits=logits)

        assert calibrated_probs.shape == probs.shape
        assert np.all((calibrated_probs >= 0) & (calibrated_probs <= 1))

    def test_confidence_level_mapping(self):
        """Test confidence level mapping."""
        calibrator = ConfidenceCalibrator(num_classes=3)

        # Test different confidence levels
        assert calibrator.get_confidence_level(0.35) == 'very_low'
        assert calibrator.get_confidence_level(0.55) == 'medium'
        assert calibrator.get_confidence_level(0.85) == 'very_high'

        # Test risk parameters
        risk_params = calibrator.get_risk_parameters('high')
        assert 'position_size' in risk_params
        assert 'stop_loss_pct' in risk_params
        assert 'take_profit_pct' in risk_params


class TestEvaluation:
    """Test evaluation metrics."""

    @pytest.fixture
    def sample_backtest_data(self):
        """Create sample backtest data."""
        n_samples = 1000
        predictions = np.random.randint(0, 3, size=n_samples)
        actual_returns = np.random.randn(n_samples) * 0.01
        return predictions, actual_returns

    def test_trading_metrics(self, sample_backtest_data):
        """Test trading metrics calculation."""
        predictions, actual_returns = sample_backtest_data

        metrics_calc = TradingMetrics()
        metrics = metrics_calc.calculate_all_metrics(predictions, actual_returns)

        # Check all metrics present
        assert 'win_rate' in metrics
        assert 'sharpe_ratio' in metrics
        assert 'max_drawdown' in metrics
        assert 'profit_factor' in metrics
        assert 'calmar_ratio' in metrics

        # Check metrics in valid ranges
        assert 0 <= metrics['win_rate'] <= 1
        assert 0 <= metrics['max_drawdown'] <= 1

    def test_ml_metrics(self):
        """Test ML classification metrics."""
        y_true = np.array([0, 1, 2, 0, 1, 2, 0, 1, 2])
        y_pred = np.array([0, 1, 2, 0, 2, 1, 0, 1, 2])

        ml_metrics = MLMetrics()
        metrics = ml_metrics.calculate_metrics(y_true, y_pred)

        assert 'accuracy' in metrics
        assert 'precision' in metrics
        assert 'recall' in metrics
        assert 'f1_score' in metrics
        assert 'per_class' in metrics

    def test_time_series_cross_validation(self):
        """Test time series cross-validation."""
        n_samples = 500
        X = np.random.randn(n_samples, 60, 128)
        y = np.random.randint(0, 3, size=n_samples)

        cv = TimeSeriesCrossValidator(n_splits=5, gap=10)
        splits = cv.split(X)

        assert len(splits) == 5

        # Check splits are sequential
        for train_idx, test_idx in splits:
            assert train_idx.max() < test_idx.min()  # No overlap


class TestMonitoring:
    """Test monitoring and drift detection."""

    def test_performance_tracker(self):
        """Test performance tracking."""
        tracker = PerformanceTracker(window_size=100)
        tracker.set_baseline(accuracy=0.75, confidence=0.70)

        # Add predictions
        for i in range(150):
            prediction = np.random.randint(0, 3)
            true_label = np.random.randint(0, 3)
            confidence = np.random.uniform(0.6, 0.9)

            tracker.update(prediction, true_label, confidence)

        # Check metrics
        metrics = tracker.get_current_metrics()
        assert 'accuracy' in metrics
        assert 'avg_confidence' in metrics
        assert metrics['sample_count'] == 100  # Window size

    def test_drift_detector(self):
        """Test drift detection."""
        # Reference data
        reference_data = np.random.randn(1000, 128)

        detector = DriftDetector(window_size=1000)
        detector.set_reference(reference_data)

        # Add data from same distribution
        for i in range(500):
            features = np.random.randn(128)
            detector.update(features)

        # No drift expected
        is_drift, metrics = detector.detect_drift()
        assert isinstance(is_drift, bool)
        assert 'avg_pvalue' in metrics

    def test_model_monitor(self):
        """Test complete model monitoring."""
        # Reference data
        reference_features = np.random.randn(1000, 128)

        monitor = ModelMonitor(
            model_name="test_model",
            performance_window=500
        )

        monitor.initialize(
            baseline_accuracy=0.75,
            baseline_confidence=0.70,
            reference_features=reference_features
        )

        # Add predictions
        for i in range(200):
            prediction = np.random.randint(0, 3)
            true_label = np.random.randint(0, 3)
            confidence = np.random.uniform(0.6, 0.9)
            features = np.random.randn(128)

            monitor.update(prediction, true_label, confidence, features)

        # Check health
        health = monitor.check_health()
        assert 'healthy' in health
        assert 'current_metrics' in health
        assert 'alerts' in health


class TestIntegration:
    """Integration tests for complete pipeline."""

    def test_end_to_end_prediction(self):
        """Test end-to-end prediction pipeline."""
        # Create sample data
        dates = pd.date_range('2024-01-01', periods=500, freq='15min')
        df = pd.DataFrame({
            'timestamp': dates,
            'open': 50000 + np.random.randn(500).cumsum() * 100,
            'high': 0,
            'low': 0,
            'close': 0,
            'volume': np.random.uniform(100, 1000, 500)
        })

        # Fill OHLC
        df['close'] = df['open'] + np.random.randn(len(df)) * 100
        df['high'] = df[['open', 'close']].max(axis=1) + np.abs(np.random.randn(len(df))) * 50
        df['low'] = df[['open', 'close']].min(axis=1) - np.abs(np.random.randn(len(df))) * 50

        # Feature engineering
        engineer = FeatureEngineer()
        features_df = engineer.engineer_features(df)

        # Label generation
        label_gen = LabelGenerator()
        labels_df = label_gen.generate_labels(features_df)

        # Create sequences
        X, y, timestamps = create_sequences(features_df, labels_df, seq_len=60)

        # Initialize ensemble
        ensemble = MLEnsemble(
            input_size=X.shape[2],
            seq_len=X.shape[1],
            num_classes=3
        )

        # Make prediction
        x_tensor = torch.from_numpy(X[0:1]).float()
        result = ensemble.predict(x_tensor, features_df=features_df.tail(60))

        # Check result
        assert result['signal'] in ['SHORT', 'NEUTRAL', 'LONG']
        assert 0 <= result['confidence'] <= 1
        assert 0 <= result['agreement'] <= 1
        assert 'regime' in result
        assert 'weights' in result


# Pytest configuration
def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
