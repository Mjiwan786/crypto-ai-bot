"""
Unit tests for PRD-001 Section 5.3 Example Signal

Tests coverage:
- Load example_signal.json file
- Validate example signal passes Pydantic validation
- Verify all required fields are present
- Verify field values are valid

Author: Crypto AI Bot Team
"""

import json
import pytest
from pathlib import Path
from datetime import datetime
from pydantic import ValidationError
from models.prd_signal_schema import TradingSignal, Side, Strategy, Regime, MACDSignal


class TestExampleSignal:
    """Test example_signal.json validation."""

    @pytest.fixture
    def example_signal_path(self):
        """Get path to example_signal.json file."""
        return Path(__file__).parent.parent.parent / "models" / "example_signal.json"

    @pytest.fixture
    def example_signal_data(self, example_signal_path):
        """Load example signal data from JSON file."""
        with open(example_signal_path, 'r') as f:
            return json.load(f)

    def test_example_signal_file_exists(self, example_signal_path):
        """Test that example_signal.json file exists."""
        assert example_signal_path.exists(), \
            f"Example signal file not found at {example_signal_path}"

    def test_example_signal_is_valid_json(self, example_signal_path):
        """Test that example_signal.json is valid JSON."""
        try:
            with open(example_signal_path, 'r') as f:
                json.load(f)
        except json.JSONDecodeError as e:
            pytest.fail(f"example_signal.json is not valid JSON: {e}")

    def test_example_signal_passes_validation(self, example_signal_data):
        """
        PRD-001 Section 5.3: Test that example signal passes Pydantic validation.

        This is the main requirement for Section 5.3 item 2:
        "Validate example signal passes Pydantic validation"
        """
        try:
            # Parse timestamp string to datetime
            signal_data = example_signal_data.copy()
            signal_data['timestamp'] = datetime.fromisoformat(signal_data['timestamp'])

            # Validate with TradingSignal model
            validated_signal = TradingSignal.model_validate(signal_data)

            # Assert validation succeeded
            assert validated_signal is not None
            assert validated_signal.signal_id == "example-signal-001"

        except ValidationError as e:
            pytest.fail(f"Example signal failed Pydantic validation: {e}")

    def test_example_signal_has_all_required_fields(self, example_signal_data):
        """Test that example signal has all required fields."""
        required_fields = {
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
            "indicators"
        }

        actual_fields = set(example_signal_data.keys())

        missing_fields = required_fields - actual_fields
        assert not missing_fields, \
            f"Example signal missing required fields: {missing_fields}"

    def test_example_signal_indicators_valid(self, example_signal_data):
        """Test that example signal indicators are valid."""
        indicators = example_signal_data.get("indicators", {})

        # Check required indicator fields
        assert "rsi_14" in indicators, "Missing rsi_14 in indicators"
        assert "macd_signal" in indicators, "Missing macd_signal in indicators"
        assert "atr_14" in indicators, "Missing atr_14 in indicators"
        assert "volume_ratio" in indicators, "Missing volume_ratio in indicators"

        # Check indicator values
        rsi = indicators["rsi_14"]
        assert 0 <= rsi <= 100, f"rsi_14 must be in [0, 100], got {rsi}"

        atr = indicators["atr_14"]
        assert atr > 0, f"atr_14 must be > 0, got {atr}"

        volume_ratio = indicators["volume_ratio"]
        assert volume_ratio > 0, f"volume_ratio must be > 0, got {volume_ratio}"

        macd = indicators["macd_signal"]
        assert macd in ["BULLISH", "BEARISH", "NEUTRAL"], \
            f"macd_signal must be BULLISH/BEARISH/NEUTRAL, got {macd}"

    def test_example_signal_metadata_valid(self, example_signal_data):
        """Test that example signal metadata is valid."""
        metadata = example_signal_data.get("metadata")

        assert metadata is not None, "Example signal should have metadata"

        # Check required metadata fields
        assert "model_version" in metadata, "Missing model_version in metadata"

        # Check optional metadata fields (if present)
        if "backtest_sharpe" in metadata:
            assert isinstance(metadata["backtest_sharpe"], (int, float)), \
                "backtest_sharpe must be numeric"

        if "latency_ms" in metadata:
            assert isinstance(metadata["latency_ms"], (int, float)), \
                "latency_ms must be numeric"
            assert metadata["latency_ms"] >= 0, \
                "latency_ms must be >= 0"

    def test_example_signal_price_relationships(self, example_signal_data):
        """Test that example signal has valid price relationships."""
        side = example_signal_data["side"]
        entry = example_signal_data["entry_price"]
        tp = example_signal_data["take_profit"]
        sl = example_signal_data["stop_loss"]

        if side == "LONG":
            assert tp > entry, \
                f"LONG signal: take_profit ({tp}) must be > entry_price ({entry})"
            assert sl < entry, \
                f"LONG signal: stop_loss ({sl}) must be < entry_price ({entry})"
        elif side == "SHORT":
            assert tp < entry, \
                f"SHORT signal: take_profit ({tp}) must be < entry_price ({entry})"
            assert sl > entry, \
                f"SHORT signal: stop_loss ({sl}) must be > entry_price ({entry})"

    def test_example_signal_confidence_in_range(self, example_signal_data):
        """Test that example signal confidence is in [0, 1]."""
        confidence = example_signal_data["confidence"]

        assert 0 <= confidence <= 1, \
            f"confidence must be in [0, 1], got {confidence}"

    def test_example_signal_position_size_valid(self, example_signal_data):
        """Test that example signal position_size_usd is valid."""
        position_size = example_signal_data["position_size_usd"]

        assert position_size > 0, \
            f"position_size_usd must be > 0, got {position_size}"
        assert position_size <= 2000, \
            f"position_size_usd must be <= 2000, got {position_size}"

    def test_example_signal_can_be_used_for_redis_publish(self, example_signal_data):
        """
        Test that example signal can be validated and used for Redis publishing.

        This tests the full integration flow from JSON to validated signal.
        """
        from agents.infrastructure.signal_validator import validate_signal_for_redis

        # Parse timestamp
        signal_data = example_signal_data.copy()
        signal_data['timestamp'] = datetime.fromisoformat(signal_data['timestamp'])

        # Validate with SignalValidator
        is_valid, validated_signal = validate_signal_for_redis(signal_data)

        assert is_valid is True, "Example signal should pass validation"
        assert validated_signal is not None

        # Get model dump (ready for Redis publish)
        redis_data = validated_signal.model_dump()

        # Verify redis_data has all expected fields
        assert "signal_id" in redis_data
        assert "trading_pair" in redis_data
        assert "side" in redis_data
        assert "entry_price" in redis_data
        assert "take_profit" in redis_data
        assert "stop_loss" in redis_data


class TestExampleSignalDocumentation:
    """Test example signal documentation."""

    def test_example_signal_has_comments_or_readme(self):
        """
        Test that example signal is documented.

        PRD-001 Section 5.3 item 3: "Document example signal in PRD Section 5.2 (already done)"

        This test verifies documentation exists. In practice, the example_signal.json
        file itself serves as documentation, and the schema is documented in
        models/prd_signal_schema.py.
        """
        # Check that schema file exists and has docstrings
        from models.prd_signal_schema import TradingSignal

        assert TradingSignal.__doc__ is not None, \
            "TradingSignal model should have docstring documentation"

        # Verify the docstring mentions PRD-001 Section 5.1
        assert "PRD-001" in TradingSignal.__doc__ or "Section 5" in TradingSignal.__doc__, \
            "TradingSignal documentation should reference PRD-001"
