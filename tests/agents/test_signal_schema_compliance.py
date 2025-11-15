"""
Integration Test: PRD-001 Signal Schema Compliance

This test validates that all signals published to Redis streams match
the exact PRD-001 specification (line 87):
    timestamp, signal_type, trading_pair, size, stop_loss, take_profit,
    confidence_score, agent_id

Test Strategy:
1. Mock signal generation from signal_processor
2. Validate against PRDSignalSchema
3. Verify all required fields present
4. Check field types and formats
5. Ensure Redis serialization is correct

Run with:
    pytest tests/agents/test_signal_schema_compliance.py -v
"""

import time
from typing import Dict, Any
import pytest
from pydantic import ValidationError

# Import PRD-001 compliant schema
from models.prd_signal_schema import PRDSignalSchema, validate_signal_for_publishing


class TestPRDSignalSchemaCompliance:
    """Test suite for PRD-001 signal schema compliance"""

    def test_valid_prd_signal(self):
        """Test that a valid PRD-001 signal passes validation"""
        signal = PRDSignalSchema(
            timestamp=time.time(),
            signal_type="entry",
            trading_pair="BTC/USD",
            size=0.5,
            stop_loss=50000.0,
            take_profit=55000.0,
            confidence_score=0.85,
            agent_id="momentum_strategy"
        )

        assert signal.timestamp > 0
        assert signal.signal_type == "entry"
        assert signal.trading_pair == "BTC/USD"
        assert signal.size == 0.5
        assert signal.confidence_score == 0.85
        assert signal.agent_id == "momentum_strategy"

    def test_all_required_fields_present(self):
        """Test that all PRD-001 required fields are present"""
        signal = PRDSignalSchema(
            timestamp=time.time(),
            signal_type="entry",
            trading_pair="BTC/USD",
            size=0.5,
            confidence_score=0.85,
            agent_id="test_agent"
        )

        # All required fields from PRD-001 line 87
        required_fields = [
            "timestamp",
            "signal_type",
            "trading_pair",
            "size",
            "confidence_score",
            "agent_id"
        ]

        signal_dict = signal.model_dump()
        for field in required_fields:
            assert field in signal_dict, f"Required field '{field}' is missing"

    def test_missing_agent_id_fails(self):
        """Test that missing agent_id causes validation error"""
        with pytest.raises(ValidationError) as exc_info:
            PRDSignalSchema(
                timestamp=time.time(),
                signal_type="entry",
                trading_pair="BTC/USD",
                size=0.5,
                confidence_score=0.85
                # Missing: agent_id
            )

        # Verify error message mentions agent_id
        error_str = str(exc_info.value)
        assert "agent_id" in error_str.lower()

    def test_invalid_signal_type_fails(self):
        """Test that invalid signal_type causes validation error"""
        with pytest.raises(ValidationError):
            PRDSignalSchema(
                timestamp=time.time(),
                signal_type="invalid_type",  # Not in: entry, exit, stop
                trading_pair="BTC/USD",
                size=0.5,
                confidence_score=0.85,
                agent_id="test"
            )

    def test_invalid_trading_pair_format_fails(self):
        """Test that invalid trading pair format fails validation"""
        with pytest.raises(ValidationError) as exc_info:
            PRDSignalSchema(
                timestamp=time.time(),
                signal_type="entry",
                trading_pair="INVALID",  # Missing '/' or '-'
                size=0.5,
                confidence_score=0.85,
                agent_id="test"
            )

        error_str = str(exc_info.value)
        assert "trading_pair" in error_str.lower()

    def test_confidence_score_range(self):
        """Test that confidence_score must be in [0, 1] range"""
        # Test below range
        with pytest.raises(ValidationError):
            PRDSignalSchema(
                timestamp=time.time(),
                signal_type="entry",
                trading_pair="BTC/USD",
                size=0.5,
                confidence_score=-0.1,  # Invalid: < 0
                agent_id="test"
            )

        # Test above range
        with pytest.raises(ValidationError):
            PRDSignalSchema(
                timestamp=time.time(),
                signal_type="entry",
                trading_pair="BTC/USD",
                size=0.5,
                confidence_score=1.5,  # Invalid: > 1
                agent_id="test"
            )

        # Test valid range
        signal = PRDSignalSchema(
            timestamp=time.time(),
            signal_type="entry",
            trading_pair="BTC/USD",
            size=0.5,
            confidence_score=0.5,  # Valid: 0 <= x <= 1
            agent_id="test"
        )
        assert 0 <= signal.confidence_score <= 1

    def test_size_must_be_positive(self):
        """Test that size must be positive"""
        with pytest.raises(ValidationError):
            PRDSignalSchema(
                timestamp=time.time(),
                signal_type="entry",
                trading_pair="BTC/USD",
                size=0.0,  # Invalid: must be > 0
                confidence_score=0.85,
                agent_id="test"
            )

        with pytest.raises(ValidationError):
            PRDSignalSchema(
                timestamp=time.time(),
                signal_type="entry",
                trading_pair="BTC/USD",
                size=-1.0,  # Invalid: negative
                confidence_score=0.85,
                agent_id="test"
            )

    def test_optional_stop_loss_take_profit(self):
        """Test that stop_loss and take_profit are optional"""
        # Without SL/TP
        signal1 = PRDSignalSchema(
            timestamp=time.time(),
            signal_type="entry",
            trading_pair="BTC/USD",
            size=0.5,
            confidence_score=0.85,
            agent_id="test"
        )
        assert signal1.stop_loss is None
        assert signal1.take_profit is None

        # With SL/TP
        signal2 = PRDSignalSchema(
            timestamp=time.time(),
            signal_type="entry",
            trading_pair="BTC/USD",
            size=0.5,
            stop_loss=50000.0,
            take_profit=55000.0,
            confidence_score=0.85,
            agent_id="test"
        )
        assert signal2.stop_loss == 50000.0
        assert signal2.take_profit == 55000.0

    def test_timestamp_validation(self):
        """Test timestamp validation (not too old or future)"""
        # Valid: current time
        signal = PRDSignalSchema(
            timestamp=time.time(),
            signal_type="entry",
            trading_pair="BTC/USD",
            size=0.5,
            confidence_score=0.85,
            agent_id="test"
        )
        assert signal.timestamp > 0

        # Invalid: too far in past (> 1 day)
        with pytest.raises(ValidationError):
            PRDSignalSchema(
                timestamp=time.time() - 86400 - 100,  # > 1 day ago
                signal_type="entry",
                trading_pair="BTC/USD",
                size=0.5,
                confidence_score=0.85,
                agent_id="test"
            )

        # Invalid: too far in future (> 1 minute)
        with pytest.raises(ValidationError):
            PRDSignalSchema(
                timestamp=time.time() + 120,  # > 1 minute in future
                signal_type="entry",
                trading_pair="BTC/USD",
                size=0.5,
                confidence_score=0.85,
                agent_id="test"
            )

    def test_redis_serialization(self):
        """Test conversion to Redis-compatible dictionary"""
        test_timestamp = time.time()
        signal = PRDSignalSchema(
            timestamp=test_timestamp,
            signal_type="entry",
            trading_pair="BTC/USD",
            size=0.5,
            stop_loss=50000.0,
            take_profit=55000.0,
            confidence_score=0.85,
            agent_id="momentum_strategy"
        )

        redis_dict = signal.to_redis_dict()

        # All values should be strings for Redis
        assert all(isinstance(v, str) for v in redis_dict.values())

        # Check required fields
        assert redis_dict["timestamp"] == str(test_timestamp)
        assert redis_dict["signal_type"] == "entry"
        assert redis_dict["trading_pair"] == "BTC/USD"
        assert redis_dict["size"] == "0.5"
        assert redis_dict["stop_loss"] == "50000.0"
        assert redis_dict["take_profit"] == "55000.0"
        assert redis_dict["confidence_score"] == "0.85"
        assert redis_dict["agent_id"] == "momentum_strategy"

    def test_legacy_signal_conversion(self):
        """Test conversion from legacy signal format to PRD-001"""
        legacy_signal = {
            "timestamp": time.time(),
            "pair": "ETH/USD",  # Legacy: "pair"
            "action": "buy",  # Legacy: "action"
            "quantity": 2.5,  # Legacy: "quantity"
            "stop_loss": 3000.0,
            "take_profit": 3500.0,
            "ai_confidence": 0.92,  # Legacy: "ai_confidence"
            "strategy": "signal_processor"  # Legacy: "strategy"
        }

        # Convert to PRD-001
        prd_signal = PRDSignalSchema.from_legacy_signal(legacy_signal)

        # Verify mapping
        assert prd_signal.trading_pair == "ETH/USD"
        assert prd_signal.signal_type == "buy"
        assert prd_signal.size == 2.5
        assert prd_signal.stop_loss == 3000.0
        assert prd_signal.take_profit == 3500.0
        assert prd_signal.confidence_score == 0.92
        assert prd_signal.agent_id == "signal_processor"

    def test_validate_signal_for_publishing(self):
        """Test the validation helper function"""
        # Valid PRD-001 format
        prd_signal_dict = {
            "timestamp": time.time(),
            "signal_type": "entry",
            "trading_pair": "BTC/USD",
            "size": 0.5,
            "stop_loss": 50000.0,
            "take_profit": 55000.0,
            "confidence_score": 0.85,
            "agent_id": "test_agent"
        }

        validated = validate_signal_for_publishing(prd_signal_dict)
        assert isinstance(validated, PRDSignalSchema)
        assert validated.agent_id == "test_agent"

        # Legacy format (should auto-convert)
        legacy_signal_dict = {
            "timestamp": time.time(),
            "pair": "ETH/USD",
            "action": "buy",
            "quantity": 1.0,
            "ai_confidence": 0.9,
            "strategy": "momentum"
        }

        validated_legacy = validate_signal_for_publishing(legacy_signal_dict)
        assert isinstance(validated_legacy, PRDSignalSchema)
        assert validated_legacy.trading_pair == "ETH/USD"
        assert validated_legacy.agent_id == "momentum"

    def test_all_signal_types(self):
        """Test all valid signal types from PRD-001"""
        valid_signal_types = [
            "entry", "exit", "stop",
            "buy", "sell",  # Extended
            "close_long", "close_short",  # Extended
            "scalp_entry", "scalp_exit"  # Extended
        ]

        for signal_type in valid_signal_types:
            signal = PRDSignalSchema(
                timestamp=time.time(),
                signal_type=signal_type,
                trading_pair="BTC/USD",
                size=0.5,
                confidence_score=0.85,
                agent_id="test"
            )
            assert signal.signal_type == signal_type.lower()

    def test_trading_pair_formats(self):
        """Test various trading pair formats"""
        valid_pairs = [
            "BTC/USD",
            "ETH/USD",
            "SOL/USD",
            "BTC-USD",  # Hyphen format
            "ETH-USDT"
        ]

        for pair in valid_pairs:
            signal = PRDSignalSchema(
                timestamp=time.time(),
                signal_type="entry",
                trading_pair=pair,
                size=0.5,
                confidence_score=0.85,
                agent_id="test"
            )
            assert "/" in signal.trading_pair.upper() or "-" in signal.trading_pair.upper()

    def test_example_signal_from_signal_processor(self):
        """Test signal that would come from signal_processor.py"""
        # Simulate current signal_processor output
        signal_processor_output = {
            "signal_id": "sig_123",
            "timestamp": time.time(),
            "pair": "BTC/USD",
            "action": "buy",
            "price": 52000.0,
            "quantity": 0.5,
            "stop_loss": 50000.0,
            "take_profit": 55000.0,
            "max_slippage_bps": 10.0,
            "strategy": "momentum_v1",
            "priority": 8,
            "ai_confidence": 0.92,
            "unified_signal": 0.88,
            "regime": "trending",
            "urgency": "high",
            "quality": "excellent"
        }

        # Convert to PRD-001 (this is what should happen in production)
        prd_signal = PRDSignalSchema.from_legacy_signal(
            signal_processor_output,
            agent_id=signal_processor_output.get("strategy", "signal_processor")
        )

        # Verify all PRD-001 fields are correct
        assert prd_signal.timestamp == signal_processor_output["timestamp"]
        assert prd_signal.signal_type == "buy"
        assert prd_signal.trading_pair == "BTC/USD"
        assert prd_signal.size == 0.5
        assert prd_signal.stop_loss == 50000.0
        assert prd_signal.take_profit == 55000.0
        assert prd_signal.confidence_score == 0.92
        assert prd_signal.agent_id == "momentum_v1"  # Mapped from strategy

        # Verify Redis format
        redis_data = prd_signal.to_redis_dict()
        assert "agent_id" in redis_data  # Critical: must have agent_id
        assert redis_data["agent_id"] == "momentum_v1"


@pytest.mark.integration
class TestSignalPublishingIntegration:
    """Integration tests for signal publishing to Redis"""

    def test_signal_publishing_workflow(self):
        """Test complete workflow from signal creation to Redis publishing"""
        # Step 1: Create signal (from signal_processor)
        raw_signal = {
            "timestamp": time.time(),
            "pair": "BTC/USD",
            "action": "entry",
            "quantity": 0.5,
            "stop_loss": 50000.0,
            "take_profit": 55000.0,
            "ai_confidence": 0.85,
            "strategy": "signal_processor"
        }

        # Step 2: Validate and convert to PRD-001
        try:
            prd_signal = validate_signal_for_publishing(raw_signal)
        except ValidationError as e:
            pytest.fail(f"Signal validation failed: {e}")

        # Step 3: Convert to Redis format
        redis_data = prd_signal.to_redis_dict()

        # Step 4: Verify ready for XADD
        assert isinstance(redis_data, dict)
        assert all(isinstance(v, str) for v in redis_data.values())
        assert "agent_id" in redis_data

        # This data is now ready for:
        # await redis_client.xadd("signals", redis_data)


# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================

def test_schema_documentation():
    """Verify PRD-001 schema documentation is accessible"""
    # This test ensures the schema is well-documented
    doc = PRDSignalSchema.__doc__
    assert doc is not None
    assert "PRD-001" in doc
    assert "timestamp" in doc
    assert "agent_id" in doc


if __name__ == "__main__":
    """Run tests directly"""
    pytest.main([__file__, "-v", "--tb=short"])
