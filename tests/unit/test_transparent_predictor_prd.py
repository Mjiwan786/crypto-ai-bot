"""
Tests for PRD-001 Compliant Transparent Predictor (Section 3.4)

Tests cover:
- Feature importance logging (top 5 features with weights)
- Feature importance storage in metadata.feature_importance field
- SHAP values for model explainability
- Model prediction publishing to events:bus stream for audit trail
- Model version logging in metadata.model_version field
- Feature documentation completeness
- Feature importance unit tests (verify top features make sense)
"""

import pytest
import logging
import time
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import numpy as np

from ml.prd_transparent_predictor import (
    PRDTransparentPredictor,
    PROMETHEUS_AVAILABLE,
    MODEL_PREDICTIONS_TOTAL,
    SHAP_AVAILABLE
)


@pytest.fixture
def mock_redis():
    """Create mock Redis client"""
    redis_mock = Mock()
    redis_mock.xadd = Mock()
    return redis_mock


@pytest.fixture
def mock_predictor():
    """Create predictor with mocked base model"""
    with patch('ml.prd_transparent_predictor.EnhancedPredictorV2') as mock:
        # Mock the base predictor
        mock_instance = Mock()
        mock_instance._fitted = True
        mock_instance.use_lightgbm = True
        mock_instance.predict_proba = Mock(return_value=0.75)
        mock_instance.feature_names_ = [
            "returns", "rsi", "adx", "slope",
            "tw_sentiment", "rd_sentiment", "news_sentiment", "sentiment_delta", "sentiment_confidence",
            "whale_inflow_ratio", "whale_outflow_ratio", "whale_net_flow",
            "whale_orderbook_imbalance", "whale_smart_money_divergence",
            "liq_imbalance", "cascade_severity", "funding_spread", "liquidation_pressure",
            "volume_surge", "volatility_regime"
        ]
        mock_instance._compute_enhanced_features = Mock(return_value=np.random.rand(20))

        # Mock LightGBM model with feature importance
        mock_model = Mock()
        mock_model.feature_importance = Mock(return_value=np.array([
            150, 120, 95, 80, 70, 65, 60, 55, 50, 45,
            40, 35, 30, 25, 20, 15, 10, 8, 5, 3
        ]))
        mock_instance.model = mock_model

        mock.return_value = mock_instance
        yield mock


@pytest.fixture
def transparent_predictor(mock_predictor, mock_redis):
    """Create transparent predictor instance"""
    return PRDTransparentPredictor(
        redis_client=mock_redis,
        model_version="v2.1",
        use_shap=False,  # Disable SHAP for most tests (tested separately)
        top_k_features=5
    )


@pytest.fixture
def market_context():
    """Create mock market context"""
    import pandas as pd
    df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=200, freq='5min'),
        'open': np.random.rand(200) * 50000,
        'high': np.random.rand(200) * 51000,
        'low': np.random.rand(200) * 49000,
        'close': np.random.rand(200) * 50000,
        'volume': np.random.rand(200) * 1000
    })

    return {
        "ohlcv_df": df,
        "current_price": 50000.0,
        "timeframe": "5m"
    }


class TestFeatureImportanceLogging:
    """Test feature importance logging (PRD-001 Section 3.4 Item 1)"""

    def test_logs_feature_importance_at_info_level(
        self,
        transparent_predictor,
        market_context,
        caplog
    ):
        """Test that feature importance is logged at INFO level"""
        with caplog.at_level(logging.INFO):
            transparent_predictor.predict_with_transparency(
                ctx=market_context,
                pair="BTC/USD"
            )

        info_logs = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_logs) > 0

    def test_logs_top_5_features(
        self,
        transparent_predictor,
        market_context,
        caplog
    ):
        """Test that top 5 features are logged"""
        with caplog.at_level(logging.INFO):
            result = transparent_predictor.predict_with_transparency(
                ctx=market_context,
                pair="BTC/USD"
            )

        # Check feature importance has 5 features
        assert len(result["feature_importance"]) == 5

    def test_log_includes_pair_and_probability(
        self,
        transparent_predictor,
        market_context,
        caplog
    ):
        """Test that log includes pair and probability"""
        with caplog.at_level(logging.INFO):
            transparent_predictor.predict_with_transparency(
                ctx=market_context,
                pair="ETH/USD"
            )

        model_logs = [r for r in caplog.records if "MODEL PREDICTION" in r.message]
        assert len(model_logs) > 0
        assert any("ETH/USD" in log.message for log in model_logs)
        assert any("Probability:" in log.message for log in model_logs)

    def test_log_includes_model_version(
        self,
        transparent_predictor,
        market_context,
        caplog
    ):
        """Test that log includes model version"""
        with caplog.at_level(logging.INFO):
            transparent_predictor.predict_with_transparency(
                ctx=market_context,
                pair="BTC/USD"
            )

        model_logs = [r for r in caplog.records if "MODEL PREDICTION" in r.message]
        assert any("Version:" in log.message and "v2.1" in log.message for log in model_logs)

    def test_log_includes_top_feature_weights(
        self,
        transparent_predictor,
        market_context,
        caplog
    ):
        """Test that log includes feature weights"""
        with caplog.at_level(logging.INFO):
            transparent_predictor.predict_with_transparency(
                ctx=market_context,
                pair="BTC/USD"
            )

        model_logs = [r for r in caplog.records if "Top Features:" in r.message]
        assert len(model_logs) > 0
        # Should have format like "feature=0.1234"
        assert any("=" in log.message for log in model_logs)


class TestFeatureImportanceMetadata:
    """Test feature importance in metadata (PRD-001 Section 3.4 Item 2)"""

    def test_result_includes_feature_importance(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that result includes feature_importance field"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        assert "feature_importance" in result
        assert isinstance(result["feature_importance"], dict)

    def test_feature_importance_has_top_k_features(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that feature importance has top K features"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        assert len(result["feature_importance"]) == 5

    def test_feature_importance_values_are_floats(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that feature importance values are floats"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        for name, importance in result["feature_importance"].items():
            assert isinstance(name, str)
            assert isinstance(importance, float)
            assert importance >= 0.0

    def test_feature_importance_sorted_descending(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that features are sorted by importance (descending)"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        importances = list(result["feature_importance"].values())
        assert importances == sorted(importances, reverse=True)


class TestSHAPValues:
    """Test SHAP values for explainability (PRD-001 Section 3.4 Item 3)"""

    @pytest.mark.skipif(not SHAP_AVAILABLE, reason="SHAP not available")
    def test_shap_values_included_when_enabled(
        self,
        mock_predictor,
        mock_redis,
        market_context
    ):
        """Test that SHAP values are included when enabled"""
        # Create predictor with SHAP enabled
        with patch('ml.prd_transparent_predictor.shap.TreeExplainer'):
            predictor = PRDTransparentPredictor(
                redis_client=mock_redis,
                model_version="v2.1",
                use_shap=True
            )

            # Mock SHAP explainer
            mock_shap_explainer = Mock()
            mock_shap_explainer.shap_values = Mock(return_value=np.random.rand(1, 20))
            predictor.shap_explainer = mock_shap_explainer

            result = predictor.predict_with_transparency(
                ctx=market_context,
                pair="BTC/USD"
            )

            # SHAP values should be included
            assert "shap_values" in result
            if result["shap_values"]:
                assert isinstance(result["shap_values"], dict)

    def test_shap_values_none_when_disabled(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that SHAP values are None when disabled"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        # SHAP disabled by default in fixture
        assert result["shap_values"] is None

    def test_shap_values_none_when_unavailable(
        self,
        mock_predictor,
        mock_redis,
        market_context
    ):
        """Test that SHAP values are None when SHAP library unavailable"""
        predictor = PRDTransparentPredictor(
            redis_client=mock_redis,
            model_version="v2.1",
            use_shap=True  # Request SHAP
        )
        predictor.shap_explainer = None  # But no explainer available

        result = predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        assert result["shap_values"] is None


class TestAuditTrailPublishing:
    """Test audit trail publishing (PRD-001 Section 3.4 Item 4)"""

    def test_publishes_to_events_bus_stream(
        self,
        transparent_predictor,
        mock_redis,
        market_context
    ):
        """Test that predictions are published to events:bus stream"""
        transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        # Should have called xadd
        mock_redis.xadd.assert_called()
        call_args = mock_redis.xadd.call_args

        # Check stream name
        assert call_args[0][0] == "events:bus"

    def test_audit_event_includes_required_fields(
        self,
        transparent_predictor,
        mock_redis,
        market_context
    ):
        """Test that audit event includes required fields"""
        transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        call_args = mock_redis.xadd.call_args
        audit_event = call_args[0][1]

        # Check required fields
        assert "event_type" in audit_event
        assert audit_event["event_type"] == "model_prediction"
        assert "timestamp" in audit_event
        assert "model_version" in audit_event
        assert "pair" in audit_event
        assert "probability" in audit_event
        assert "feature_importance" in audit_event

    def test_audit_event_has_maxlen_limit(
        self,
        transparent_predictor,
        mock_redis,
        market_context
    ):
        """Test that audit stream has maxlen limit"""
        transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        call_args = mock_redis.xadd.call_args
        assert "maxlen" in call_args[1]
        assert call_args[1]["maxlen"] == 10000

    def test_no_publish_when_redis_unavailable(
        self,
        mock_predictor,
        market_context
    ):
        """Test that no error when redis unavailable"""
        predictor = PRDTransparentPredictor(
            redis_client=None,  # No redis
            model_version="v2.1"
        )

        # Should not raise error
        result = predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        assert result is not None

    def test_no_publish_when_audit_disabled(
        self,
        mock_predictor,
        mock_redis,
        market_context
    ):
        """Test that no publish when audit disabled"""
        predictor = PRDTransparentPredictor(
            redis_client=mock_redis,
            model_version="v2.1",
            publish_audit=False  # Disabled
        )

        predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        # Should not have called xadd
        mock_redis.xadd.assert_not_called()


class TestModelVersion:
    """Test model version logging (PRD-001 Section 3.4 Item 7)"""

    def test_result_includes_model_version(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that result includes model_version field"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        assert "model_version" in result
        assert result["model_version"] == "v2.1"

    def test_custom_model_version(
        self,
        mock_predictor,
        mock_redis,
        market_context
    ):
        """Test that custom model version can be set"""
        predictor = PRDTransparentPredictor(
            redis_client=mock_redis,
            model_version="v3.0-beta"
        )

        result = predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        assert result["model_version"] == "v3.0-beta"


class TestPrometheusMetrics:
    """Test Prometheus metrics"""

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_emits_predictions_counter(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that predictions emit counter metric"""
        initial_count = MODEL_PREDICTIONS_TOTAL.labels(
            model_version="v2.1",
            pair="BTC/USD"
        )._value.get()

        transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        final_count = MODEL_PREDICTIONS_TOTAL.labels(
            model_version="v2.1",
            pair="BTC/USD"
        )._value.get()

        assert final_count > initial_count

    @pytest.mark.skipif(not PROMETHEUS_AVAILABLE, reason="Prometheus not available")
    def test_counter_labels_by_pair(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that counter is labeled by trading pair"""
        transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="ETH/USD"
        )

        count = MODEL_PREDICTIONS_TOTAL.labels(
            model_version="v2.1",
            pair="ETH/USD"
        )._value.get()

        assert count is not None


class TestResultStructure:
    """Test prediction result structure"""

    def test_result_includes_probability(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that result includes probability"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        assert "probability" in result
        assert isinstance(result["probability"], float)
        assert 0.0 <= result["probability"] <= 1.0

    def test_result_includes_features(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that result includes computed features"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        assert "features" in result
        assert isinstance(result["features"], dict)
        assert len(result["features"]) == 20  # All 20 features

    def test_result_includes_timestamp(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that result includes timestamp"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        assert "timestamp" in result
        assert isinstance(result["timestamp"], float)

    def test_result_includes_pair(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that result includes pair"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="ETH/USD"
        )

        assert "pair" in result
        assert result["pair"] == "ETH/USD"

    def test_result_includes_latency_ms(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that result includes latency measurement"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], float)
        assert result["latency_ms"] >= 0


class TestFeatureDocumentation:
    """Test feature documentation (PRD-001 Section 3.4 Item 5)"""

    def test_get_feature_documentation_returns_list(
        self,
        transparent_predictor
    ):
        """Test that get_feature_documentation returns list"""
        docs = transparent_predictor.get_feature_documentation()
        assert isinstance(docs, list)

    def test_feature_documentation_has_all_features(
        self,
        transparent_predictor
    ):
        """Test that documentation includes all 20 features"""
        docs = transparent_predictor.get_feature_documentation()
        assert len(docs) == 20

    def test_each_feature_has_required_fields(
        self,
        transparent_predictor
    ):
        """Test that each feature has name, formula, purpose, expected_range"""
        docs = transparent_predictor.get_feature_documentation()

        for feature_doc in docs:
            assert "name" in feature_doc
            assert "formula" in feature_doc
            assert "purpose" in feature_doc
            assert "expected_range" in feature_doc

    def test_feature_names_match_model_features(
        self,
        transparent_predictor
    ):
        """Test that documented features match model feature names"""
        docs = transparent_predictor.get_feature_documentation()
        doc_names = {doc["name"] for doc in docs}

        model_names = set(transparent_predictor.predictor.feature_names_)

        assert doc_names == model_names


class TestTopFeaturesValidity:
    """Test that top features make sense (PRD-001 Section 3.4 Item 8)"""

    def test_returns_is_top_feature(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that 'returns' is among top features (should be highly predictive)"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        # Returns should be in top 5 features (it's the strongest predictor)
        assert "returns" in result["feature_importance"]

    def test_top_features_are_high_value(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that top features have meaningful importance values"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        # Top features should have non-zero importance
        for name, importance in result["feature_importance"].items():
            assert importance > 0.0

    def test_technical_features_in_top_5(
        self,
        transparent_predictor,
        market_context
    ):
        """Test that at least one technical feature is in top 5"""
        result = transparent_predictor.predict_with_transparency(
            ctx=market_context,
            pair="BTC/USD"
        )

        technical_features = {"returns", "rsi", "adx", "slope"}
        top_features = set(result["feature_importance"].keys())

        # At least one technical feature should be in top 5
        assert len(technical_features & top_features) > 0


class TestGetMetrics:
    """Test get_metrics method"""

    def test_get_metrics_returns_dict(
        self,
        transparent_predictor
    ):
        """Test that get_metrics returns dictionary"""
        metrics = transparent_predictor.get_metrics()
        assert isinstance(metrics, dict)

    def test_metrics_include_model_version(
        self,
        transparent_predictor
    ):
        """Test that metrics include model_version"""
        metrics = transparent_predictor.get_metrics()
        assert "model_version" in metrics
        assert metrics["model_version"] == "v2.1"

    def test_metrics_include_shap_enabled(
        self,
        transparent_predictor
    ):
        """Test that metrics include shap_enabled"""
        metrics = transparent_predictor.get_metrics()
        assert "shap_enabled" in metrics
        assert isinstance(metrics["shap_enabled"], bool)

    def test_metrics_include_audit_enabled(
        self,
        transparent_predictor
    ):
        """Test that metrics include audit_enabled"""
        metrics = transparent_predictor.get_metrics()
        assert "audit_enabled" in metrics
        assert isinstance(metrics["audit_enabled"], bool)

    def test_metrics_include_num_features(
        self,
        transparent_predictor
    ):
        """Test that metrics include num_features"""
        metrics = transparent_predictor.get_metrics()
        assert "num_features" in metrics
        assert metrics["num_features"] == 20
