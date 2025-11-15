"""
Unit tests for PRD-001 Section 5.2 Schema Validation

Tests coverage:
- SignalValidator class initialization
- validate_signal() with valid signals
- validate_signal() with invalid signals (missing fields, wrong types, out-of-range values)
- ERROR level logging on validation failures
- Prometheus counter emission on validation failures
- Signal rejection (do not publish invalid signals)
- Regression test: signal schema matches API expectations
- validate_signal_for_redis() convenience function

Author: Crypto AI Bot Team
"""

import pytest
from datetime import datetime
from unittest.mock import patch, Mock
from agents.infrastructure.signal_validator import (
    SignalValidator,
    get_signal_validator,
    validate_signal_for_redis
)
from models.prd_signal_schema import (
    Side,
    Strategy,
    Regime,
    MACDSignal
)


class TestSignalValidatorInit:
    """Test SignalValidator initialization."""

    def test_init(self, caplog):
        """Test SignalValidator initialization."""
        import logging
        with caplog.at_level(logging.INFO):
            validator = SignalValidator()

        assert validator.total_validations == 0
        assert validator.total_failures == 0
        assert "SignalValidator initialized" in caplog.text
        assert "PRD-001 Section 5.2" in caplog.text


class TestValidateSignalValid:
    """Test validate_signal() with valid signals."""

    def test_validate_valid_long_signal(self):
        """Test validation of valid LONG signal."""
        validator = SignalValidator()

        signal = {
            "signal_id": "test-001",
            "timestamp": datetime.now(),
            "trading_pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        is_valid, validated = validator.validate_signal(signal)

        assert is_valid is True
        assert validated is not None
        assert validated.signal_id == "test-001"
        assert validated.side == Side.LONG
        assert validated.entry_price == 50000.0
        assert validator.total_validations == 1
        assert validator.total_failures == 0

    def test_validate_valid_short_signal(self):
        """Test validation of valid SHORT signal."""
        validator = SignalValidator()

        signal = {
            "signal_id": "test-002",
            "timestamp": datetime.now(),
            "trading_pair": "ETH/USD",
            "side": "SHORT",
            "strategy": "TREND",
            "regime": "TRENDING_DOWN",
            "entry_price": 3000.0,
            "take_profit": 2900.0,
            "stop_loss": 3050.0,
            "confidence": 0.75,
            "position_size_usd": 500.0,
            "indicators": {
                "rsi_14": 40.0,
                "macd_signal": "BEARISH",
                "atr_14": 80.0,
                "volume_ratio": 1.2
            }
        }

        is_valid, validated = validator.validate_signal(signal)

        assert is_valid is True
        assert validated is not None
        assert validated.side == Side.SHORT
        assert validator.total_validations == 1
        assert validator.total_failures == 0

    def test_validate_valid_signal_with_metadata(self):
        """Test validation of valid signal with metadata."""
        validator = SignalValidator()

        signal = {
            "signal_id": "test-003",
            "timestamp": datetime.now(),
            "trading_pair": "SOL/USD",
            "side": "LONG",
            "strategy": "BREAKOUT",
            "regime": "VOLATILE",
            "entry_price": 100.0,
            "take_profit": 105.0,
            "stop_loss": 98.0,
            "confidence": 0.90,
            "position_size_usd": 800.0,
            "indicators": {
                "rsi_14": 55.0,
                "macd_signal": "BULLISH",
                "atr_14": 5.0,
                "volume_ratio": 1.3
            },
            "metadata": {
                "model_version": "v1.5.0",
                "backtest_sharpe": 2.8,
                "latency_ms": 15.0
            }
        }

        is_valid, validated = validator.validate_signal(signal)

        assert is_valid is True
        assert validated is not None
        assert validated.metadata is not None
        assert validated.metadata.model_version == "v1.5.0"


class TestValidateSignalInvalid:
    """Test validate_signal() with invalid signals."""

    def test_validate_missing_required_field(self, caplog):
        """Test validation fails with missing required field."""
        import logging
        validator = SignalValidator()

        signal = {
            "signal_id": "test-fail",
            "timestamp": datetime.now(),
            # Missing trading_pair
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        with caplog.at_level(logging.ERROR):
            is_valid, validated = validator.validate_signal(signal)

        assert is_valid is False
        assert validated is None
        assert validator.total_validations == 1
        assert validator.total_failures == 1
        assert "[SCHEMA VALIDATION FAILED]" in caplog.text
        assert "trading_pair" in caplog.text.lower()

    def test_validate_wrong_type_field(self, caplog):
        """Test validation fails with wrong type field."""
        import logging
        validator = SignalValidator()

        signal = {
            "signal_id": "test-fail",
            "timestamp": datetime.now(),
            "trading_pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": "not_a_number",  # Wrong type (string instead of float)
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        with caplog.at_level(logging.ERROR):
            is_valid, validated = validator.validate_signal(signal)

        assert is_valid is False
        assert validated is None
        assert "[SCHEMA VALIDATION FAILED]" in caplog.text

    def test_validate_out_of_range_confidence(self, caplog):
        """Test validation fails with out-of-range confidence."""
        import logging
        validator = SignalValidator()

        signal = {
            "signal_id": "test-fail",
            "timestamp": datetime.now(),
            "trading_pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 1.5,  # Out of range (must be in [0, 1])
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        with caplog.at_level(logging.ERROR):
            is_valid, validated = validator.validate_signal(signal)

        assert is_valid is False
        assert validated is None
        assert "[SCHEMA VALIDATION FAILED]" in caplog.text
        assert "confidence" in caplog.text.lower()

    def test_validate_out_of_range_rsi(self, caplog):
        """Test validation fails with out-of-range RSI."""
        import logging
        validator = SignalValidator()

        signal = {
            "signal_id": "test-fail",
            "timestamp": datetime.now(),
            "trading_pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 150.0,  # Out of range (must be in [0, 100])
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        with caplog.at_level(logging.ERROR):
            is_valid, validated = validator.validate_signal(signal)

        assert is_valid is False
        assert validated is None
        assert "[SCHEMA VALIDATION FAILED]" in caplog.text

    def test_validate_invalid_price_relationship_long(self, caplog):
        """Test validation fails with invalid LONG price relationship."""
        import logging
        validator = SignalValidator()

        signal = {
            "signal_id": "test-fail",
            "timestamp": datetime.now(),
            "trading_pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 49000.0,  # Invalid: take_profit < entry_price for LONG
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        with caplog.at_level(logging.ERROR):
            is_valid, validated = validator.validate_signal(signal)

        assert is_valid is False
        assert validated is None
        assert "[SCHEMA VALIDATION FAILED]" in caplog.text

    def test_validate_invalid_price_relationship_short(self, caplog):
        """Test validation fails with invalid SHORT price relationship."""
        import logging
        validator = SignalValidator()

        signal = {
            "signal_id": "test-fail",
            "timestamp": datetime.now(),
            "trading_pair": "ETH/USD",
            "side": "SHORT",
            "strategy": "TREND",
            "regime": "TRENDING_DOWN",
            "entry_price": 3000.0,
            "take_profit": 3100.0,  # Invalid: take_profit > entry_price for SHORT
            "stop_loss": 3050.0,
            "confidence": 0.75,
            "position_size_usd": 500.0,
            "indicators": {
                "rsi_14": 40.0,
                "macd_signal": "BEARISH",
                "atr_14": 80.0,
                "volume_ratio": 1.2
            }
        }

        with caplog.at_level(logging.ERROR):
            is_valid, validated = validator.validate_signal(signal)

        assert is_valid is False
        assert validated is None
        assert "[SCHEMA VALIDATION FAILED]" in caplog.text

    def test_validate_position_size_above_limit(self, caplog):
        """Test validation fails with position_size_usd > 2000."""
        import logging
        validator = SignalValidator()

        signal = {
            "signal_id": "test-fail",
            "timestamp": datetime.now(),
            "trading_pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 2500.0,  # Above limit (must be <= 2000)
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        with caplog.at_level(logging.ERROR):
            is_valid, validated = validator.validate_signal(signal)

        assert is_valid is False
        assert validated is None
        assert "[SCHEMA VALIDATION FAILED]" in caplog.text


class TestPrometheusMetrics:
    """Test Prometheus counter emission."""

    @patch('agents.infrastructure.signal_validator.PROMETHEUS_AVAILABLE', True)
    @patch('agents.infrastructure.signal_validator.SIGNAL_SCHEMA_ERRORS')
    def test_prometheus_counter_emitted_on_failure(self, mock_counter):
        """Test Prometheus counter is emitted on validation failure."""
        validator = SignalValidator()

        # Invalid signal (missing trading_pair)
        signal = {
            "signal_id": "test-fail",
            "timestamp": datetime.now(),
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        is_valid, validated = validator.validate_signal(signal)

        assert is_valid is False
        # Prometheus counter should be called
        assert mock_counter.labels.called


class TestGetMetrics:
    """Test metrics retrieval."""

    def test_get_metrics_initial(self):
        """Test metrics with no validations."""
        validator = SignalValidator()

        metrics = validator.get_metrics()

        assert metrics["total_validations"] == 0
        assert metrics["total_failures"] == 0
        assert metrics["failure_rate"] == 0.0

    def test_get_metrics_after_validations(self):
        """Test metrics after some validations."""
        validator = SignalValidator()

        # Valid signal
        valid_signal = {
            "signal_id": "test-001",
            "timestamp": datetime.now(),
            "trading_pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        # Invalid signal (missing trading_pair)
        invalid_signal = {
            "signal_id": "test-fail",
            "timestamp": datetime.now(),
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        # 2 valid, 1 invalid
        validator.validate_signal(valid_signal)
        validator.validate_signal(valid_signal)
        validator.validate_signal(invalid_signal)

        metrics = validator.get_metrics()

        assert metrics["total_validations"] == 3
        assert metrics["total_failures"] == 1
        assert abs(metrics["failure_rate"] - 0.333) < 0.01


class TestResetStats:
    """Test statistics reset."""

    def test_reset_stats(self, caplog):
        """Test statistics reset."""
        import logging
        validator = SignalValidator()

        # Make some validations
        valid_signal = {
            "signal_id": "test-001",
            "timestamp": datetime.now(),
            "trading_pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        validator.validate_signal(valid_signal)
        assert validator.total_validations == 1

        # Reset
        with caplog.at_level(logging.INFO):
            validator.reset_stats()

        assert validator.total_validations == 0
        assert validator.total_failures == 0
        assert "SignalValidator statistics reset" in caplog.text


class TestConvenienceFunctions:
    """Test convenience functions."""

    def test_get_signal_validator_singleton(self):
        """Test get_signal_validator() returns singleton."""
        validator1 = get_signal_validator()
        validator2 = get_signal_validator()

        assert validator1 is validator2

    def test_validate_signal_for_redis_valid(self):
        """Test validate_signal_for_redis() with valid signal."""
        signal = {
            "signal_id": "test-001",
            "timestamp": datetime.now(),
            "trading_pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        is_valid, validated = validate_signal_for_redis(signal)

        assert is_valid is True
        assert validated is not None

    def test_validate_signal_for_redis_invalid(self):
        """Test validate_signal_for_redis() with invalid signal."""
        # Missing trading_pair
        signal = {
            "signal_id": "test-fail",
            "timestamp": datetime.now(),
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            }
        }

        is_valid, validated = validate_signal_for_redis(signal)

        assert is_valid is False
        assert validated is None


class TestAPIRegressionCompatibility:
    """
    PRD-001 Section 5.2: Regression test to ensure signal schema matches API expectations.

    This test ensures that the TradingSignal schema has all expected fields
    with correct types that match the API contract.
    """

    def test_signal_schema_api_compatibility(self):
        """Test that signal schema has all expected API fields with correct types."""
        signal = {
            "signal_id": "api-test-001",
            "timestamp": datetime.now(),
            "trading_pair": "BTC/USD",
            "side": "LONG",
            "strategy": "SCALPER",
            "regime": "TRENDING_UP",
            "entry_price": 50000.0,
            "take_profit": 51000.0,
            "stop_loss": 49500.0,
            "confidence": 0.85,
            "position_size_usd": 1000.0,
            "indicators": {
                "rsi_14": 60.0,
                "macd_signal": "BULLISH",
                "atr_14": 100.0,
                "volume_ratio": 1.5
            },
            "metadata": {
                "model_version": "v1.0.0",
                "backtest_sharpe": 2.5,
                "latency_ms": 10.0
            }
        }

        is_valid, validated = validate_signal_for_redis(signal)

        assert is_valid is True
        assert validated is not None

        # Verify all expected fields exist
        assert hasattr(validated, "signal_id")
        assert hasattr(validated, "timestamp")
        assert hasattr(validated, "trading_pair")
        assert hasattr(validated, "side")
        assert hasattr(validated, "strategy")
        assert hasattr(validated, "regime")
        assert hasattr(validated, "entry_price")
        assert hasattr(validated, "take_profit")
        assert hasattr(validated, "stop_loss")
        assert hasattr(validated, "confidence")
        assert hasattr(validated, "position_size_usd")
        assert hasattr(validated, "indicators")
        assert hasattr(validated, "metadata")

        # Verify field types
        assert isinstance(validated.signal_id, str)
        assert isinstance(validated.trading_pair, str)
        assert isinstance(validated.entry_price, float)
        assert isinstance(validated.take_profit, float)
        assert isinstance(validated.stop_loss, float)
        assert isinstance(validated.confidence, float)
        assert isinstance(validated.position_size_usd, float)

        # Verify indicators subfields
        assert hasattr(validated.indicators, "rsi_14")
        assert hasattr(validated.indicators, "macd_signal")
        assert hasattr(validated.indicators, "atr_14")
        assert hasattr(validated.indicators, "volume_ratio")

        # Verify metadata subfields
        assert validated.metadata is not None
        assert hasattr(validated.metadata, "model_version")
        assert hasattr(validated.metadata, "backtest_sharpe")
        assert hasattr(validated.metadata, "latency_ms")

    def test_signal_schema_field_names_match_api(self):
        """Test that field names exactly match API expectations (no typos)."""
        from models.prd_signal_schema import TradingSignal

        # Get model fields
        fields = TradingSignal.model_fields

        # Verify exact field names (API contract)
        expected_fields = {
            "signal_id",
            "timestamp",
            "trading_pair",
            "side",
            "strategy",
            "regime",
            "entry_price",
            "take_profit",
            "stop_loss",
            "confidence",
            "position_size_usd",
            "indicators",
            "metadata"
        }

        actual_fields = set(fields.keys())

        # All expected fields must be present
        assert expected_fields.issubset(actual_fields), \
            f"Missing fields: {expected_fields - actual_fields}"
