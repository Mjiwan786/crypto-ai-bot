"""
Tests for PRD-001 Compliant Publisher (tests/unit/test_prd_publisher.py)

Validates that the PRD publisher:
1. Signal schema matches PRD-001 exactly
2. Stream names follow PRD-001 naming convention
3. Price relationship validation works correctly
4. Legacy signal adaptation preserves data correctly
5. Redis dict conversion produces valid string values

Run with: pytest tests/unit/test_prd_publisher.py -v
"""

import pytest
from datetime import datetime, timezone
from uuid import UUID

from agents.infrastructure.prd_publisher import (
    PRDSignal,
    PRDIndicators,
    PRDMetadata,
    PRDPnLUpdate,
    PRDEvent,
    PRDPublisher,
    Side,
    Strategy,
    Regime,
    MACDSignal,
    create_prd_signal,
    adapt_legacy_signal,
)


class TestPRDSignalSchema:
    """Tests for PRD-001 signal schema compliance."""

    def test_signal_has_uuid_id(self):
        """PRD-001: signal_id must be UUID v4"""
        signal = create_prd_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
        )
        # Should be valid UUID
        uuid_obj = UUID(signal.signal_id)
        assert uuid_obj.version == 4

    def test_signal_has_iso8601_timestamp(self):
        """PRD-001: timestamp must be ISO8601 UTC string"""
        signal = create_prd_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
        )
        # Should be parseable as ISO8601
        dt = datetime.fromisoformat(signal.timestamp.replace("Z", "+00:00"))
        assert dt.tzinfo is not None

    def test_signal_side_enum_values(self):
        """PRD-001: side must be LONG or SHORT (not buy/sell)"""
        assert Side.LONG.value == "LONG"
        assert Side.SHORT.value == "SHORT"

        signal = create_prd_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
        )
        assert signal.side in [Side.LONG, Side.SHORT, "LONG", "SHORT"]

    def test_signal_strategy_enum_values(self):
        """PRD-001: strategy must be one of SCALPER, TREND, MEAN_REVERSION, BREAKOUT"""
        assert Strategy.SCALPER.value == "SCALPER"
        assert Strategy.TREND.value == "TREND"
        assert Strategy.MEAN_REVERSION.value == "MEAN_REVERSION"
        assert Strategy.BREAKOUT.value == "BREAKOUT"

    def test_signal_regime_enum_values(self):
        """PRD-001: regime must be one of TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE"""
        assert Regime.TRENDING_UP.value == "TRENDING_UP"
        assert Regime.TRENDING_DOWN.value == "TRENDING_DOWN"
        assert Regime.RANGING.value == "RANGING"
        assert Regime.VOLATILE.value == "VOLATILE"

    def test_signal_required_fields_present(self):
        """PRD-001: All required fields must be present"""
        signal = create_prd_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
        )

        # Check all PRD-001 required fields
        assert hasattr(signal, "signal_id")
        assert hasattr(signal, "timestamp")
        assert hasattr(signal, "pair")
        assert hasattr(signal, "side")
        assert hasattr(signal, "strategy")
        assert hasattr(signal, "regime")
        assert hasattr(signal, "entry_price")
        assert hasattr(signal, "take_profit")
        assert hasattr(signal, "stop_loss")
        assert hasattr(signal, "confidence")
        assert hasattr(signal, "position_size_usd")

    def test_signal_pair_normalization(self):
        """PRD-001: Pair should be normalized to use forward slash"""
        signal = create_prd_signal(
            pair="BTC-USD",  # With dash
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
        )
        assert signal.pair == "BTC/USD"  # Normalized with slash


class TestPriceRelationshipValidation:
    """Tests for PRD-001 price relationship validation."""

    def test_long_signal_tp_must_be_above_entry(self):
        """PRD-001: LONG take_profit > entry_price"""
        with pytest.raises(ValueError, match="take_profit.*must be > entry_price"):
            PRDSignal(
                pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.TRENDING_UP,
                entry_price=50000.0,
                take_profit=48000.0,  # Invalid: below entry
                stop_loss=49000.0,
                confidence=0.85,
                position_size_usd=500.0,
            )

    def test_long_signal_sl_must_be_below_entry(self):
        """PRD-001: LONG stop_loss < entry_price"""
        with pytest.raises(ValueError, match="stop_loss.*must be < entry_price"):
            PRDSignal(
                pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.TRENDING_UP,
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=51000.0,  # Invalid: above entry
                confidence=0.85,
                position_size_usd=500.0,
            )

    def test_short_signal_tp_must_be_below_entry(self):
        """PRD-001: SHORT take_profit < entry_price"""
        with pytest.raises(ValueError, match="take_profit.*must be < entry_price"):
            PRDSignal(
                pair="BTC/USD",
                side=Side.SHORT,
                strategy=Strategy.SCALPER,
                regime=Regime.TRENDING_DOWN,
                entry_price=50000.0,
                take_profit=52000.0,  # Invalid: above entry
                stop_loss=51000.0,
                confidence=0.85,
                position_size_usd=500.0,
            )

    def test_short_signal_sl_must_be_above_entry(self):
        """PRD-001: SHORT stop_loss > entry_price"""
        with pytest.raises(ValueError, match="stop_loss.*must be > entry_price"):
            PRDSignal(
                pair="BTC/USD",
                side=Side.SHORT,
                strategy=Strategy.SCALPER,
                regime=Regime.TRENDING_DOWN,
                entry_price=50000.0,
                take_profit=48000.0,
                stop_loss=49000.0,  # Invalid: below entry
                confidence=0.85,
                position_size_usd=500.0,
            )

    def test_valid_long_signal(self):
        """PRD-001: Valid LONG signal with correct price relationships"""
        signal = PRDSignal(
            pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=52000.0,  # Valid: above entry
            stop_loss=49000.0,    # Valid: below entry
            confidence=0.85,
            position_size_usd=500.0,
        )
        assert signal.entry_price == 50000.0
        assert signal.take_profit == 52000.0
        assert signal.stop_loss == 49000.0

    def test_valid_short_signal(self):
        """PRD-001: Valid SHORT signal with correct price relationships"""
        signal = PRDSignal(
            pair="BTC/USD",
            side=Side.SHORT,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_DOWN,
            entry_price=50000.0,
            take_profit=48000.0,  # Valid: below entry
            stop_loss=51000.0,    # Valid: above entry
            confidence=0.85,
            position_size_usd=500.0,
        )
        assert signal.entry_price == 50000.0
        assert signal.take_profit == 48000.0
        assert signal.stop_loss == 51000.0


class TestConfidenceValidation:
    """Tests for confidence score validation."""

    def test_confidence_must_be_between_0_and_1(self):
        """PRD-001: confidence must be in [0, 1]"""
        # Test below 0
        with pytest.raises(ValueError):
            create_prd_signal(
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                regime="TRENDING_UP",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=-0.5,  # Invalid
            )

        # Test above 1
        with pytest.raises(ValueError):
            create_prd_signal(
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                regime="TRENDING_UP",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=1.5,  # Invalid
            )

    def test_valid_confidence_values(self):
        """PRD-001: Valid confidence values [0, 1]"""
        # Minimum
        signal_min = create_prd_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.0,
        )
        assert signal_min.confidence == 0.0

        # Maximum
        signal_max = create_prd_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=1.0,
        )
        assert signal_max.confidence == 1.0


class TestPositionSizeValidation:
    """Tests for position size validation."""

    def test_position_size_must_be_positive(self):
        """PRD-001: position_size_usd > 0"""
        with pytest.raises(ValueError):
            create_prd_signal(
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                regime="TRENDING_UP",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=0.85,
                position_size_usd=0.0,  # Invalid
            )

    def test_position_size_max_2000(self):
        """PRD-001: position_size_usd <= 2000"""
        with pytest.raises(ValueError):
            create_prd_signal(
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                regime="TRENDING_UP",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=0.85,
                position_size_usd=3000.0,  # Invalid: exceeds max
            )


class TestStreamKeyGeneration:
    """Tests for PRD-001 stream key naming."""

    def test_paper_mode_stream_key(self):
        """PRD-001: Paper mode stream is signals:paper:<PAIR>"""
        signal = create_prd_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
        )
        assert signal.get_stream_key("paper") == "signals:paper:BTC-USD"

    def test_live_mode_stream_key(self):
        """PRD-001: Live mode stream is signals:live:<PAIR>"""
        signal = create_prd_signal(
            pair="ETH/USD",
            side="SHORT",
            strategy="TREND",
            regime="TRENDING_DOWN",
            entry_price=3000.0,
            take_profit=2800.0,
            stop_loss=3100.0,
            confidence=0.75,
        )
        assert signal.get_stream_key("live") == "signals:live:ETH-USD"

    def test_stream_key_uses_dash_not_slash(self):
        """Stream key uses dash instead of slash for safety"""
        signal = create_prd_signal(
            pair="SOL/USD",  # Input with slash
            side="LONG",
            strategy="BREAKOUT",
            regime="VOLATILE",
            entry_price=100.0,
            take_profit=110.0,
            stop_loss=95.0,
            confidence=0.65,
        )
        stream_key = signal.get_stream_key("paper")
        assert "/" not in stream_key  # No slashes in stream name
        assert "SOL-USD" in stream_key


class TestRedisDict:
    """Tests for Redis dict conversion."""

    def test_all_values_are_strings(self):
        """Redis XADD requires all values to be strings"""
        signal = create_prd_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
        )
        redis_dict = signal.to_redis_dict()

        for key, value in redis_dict.items():
            assert isinstance(value, str), f"Value for {key} is {type(value)}, expected str"

    def test_redis_dict_has_required_fields(self):
        """Redis dict contains all PRD-001 required fields"""
        signal = create_prd_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
        )
        redis_dict = signal.to_redis_dict()

        required_fields = [
            "signal_id",
            "timestamp",
            "pair",
            "side",
            "strategy",
            "regime",
            "entry_price",
            "take_profit",
            "stop_loss",
            "confidence",
            "position_size_usd",
        ]

        for field in required_fields:
            assert field in redis_dict, f"Missing required field: {field}"


class TestLegacySignalAdaptation:
    """Tests for legacy signal format adaptation."""

    def test_adapt_buy_to_long(self):
        """Legacy 'buy' side maps to PRD 'LONG'"""
        legacy = {
            "pair": "BTC/USD",
            "side": "buy",
            "entry": 50000.0,
            "sl": 49000.0,
            "tp": 52000.0,
            "confidence": 0.85,
            "strategy": "scalper",
        }
        adapted = adapt_legacy_signal(legacy)
        assert adapted.side == Side.LONG

    def test_adapt_sell_to_short(self):
        """Legacy 'sell' side maps to PRD 'SHORT'"""
        legacy = {
            "pair": "BTC/USD",
            "side": "sell",
            "entry": 50000.0,
            "sl": 51000.0,  # SL above entry for short
            "tp": 48000.0,  # TP below entry for short
            "confidence": 0.85,
            "strategy": "scalper",
        }
        adapted = adapt_legacy_signal(legacy)
        assert adapted.side == Side.SHORT

    def test_adapt_field_names(self):
        """Legacy field names map correctly to PRD field names"""
        legacy = {
            "pair": "ETH/USD",
            "side": "buy",
            "entry": 3000.0,      # Should map to entry_price
            "sl": 2900.0,         # Should map to stop_loss
            "tp": 3200.0,         # Should map to take_profit
            "confidence": 0.72,
            "strategy": "momentum_v1",
        }
        adapted = adapt_legacy_signal(legacy)

        assert adapted.pair == "ETH/USD"
        assert adapted.entry_price == 3000.0
        assert adapted.stop_loss == 2900.0
        assert adapted.take_profit == 3200.0
        assert adapted.confidence == 0.72

    def test_adapt_strategy_names(self):
        """Legacy strategy names map to PRD enum values"""
        test_cases = [
            ("scalper", Strategy.SCALPER),
            ("scalping", Strategy.SCALPER),
            ("trend", Strategy.TREND),
            ("trend_following", Strategy.TREND),
            ("momentum_v1", Strategy.TREND),
            ("mean_reversion", Strategy.MEAN_REVERSION),
            ("breakout", Strategy.BREAKOUT),
        ]

        for legacy_strategy, expected in test_cases:
            legacy = {
                "pair": "BTC/USD",
                "side": "buy",
                "entry": 50000.0,
                "sl": 49000.0,
                "tp": 52000.0,
                "confidence": 0.5,
                "strategy": legacy_strategy,
            }
            adapted = adapt_legacy_signal(legacy)
            assert adapted.strategy == expected, f"Failed for {legacy_strategy}"


class TestIndicators:
    """Tests for PRD-001 indicator schema."""

    def test_indicators_rsi_validation(self):
        """PRD-001: RSI must be in [0, 100]"""
        # Valid RSI
        indicators = PRDIndicators(
            rsi_14=50.0,
            macd_signal=MACDSignal.BULLISH,
            atr_14=100.0,
            volume_ratio=1.5,
        )
        assert indicators.rsi_14 == 50.0

        # Invalid RSI
        with pytest.raises(ValueError):
            PRDIndicators(
                rsi_14=150.0,  # Invalid: above 100
                macd_signal=MACDSignal.BULLISH,
                atr_14=100.0,
                volume_ratio=1.5,
            )

    def test_indicators_atr_must_be_positive(self):
        """PRD-001: ATR must be > 0"""
        with pytest.raises(ValueError):
            PRDIndicators(
                rsi_14=50.0,
                macd_signal=MACDSignal.BULLISH,
                atr_14=0.0,  # Invalid: not positive
                volume_ratio=1.5,
            )

    def test_indicators_volume_ratio_must_be_positive(self):
        """PRD-001: Volume ratio must be > 0"""
        with pytest.raises(ValueError):
            PRDIndicators(
                rsi_14=50.0,
                macd_signal=MACDSignal.BULLISH,
                atr_14=100.0,
                volume_ratio=-1.0,  # Invalid: negative
            )


class TestPnLUpdate:
    """Tests for PRD-001 PnL update schema."""

    def test_pnl_update_has_required_fields(self):
        """PRD-001: PnL update has all required fields"""
        pnl = PRDPnLUpdate(
            equity=10500.0,
            realized_pnl=500.0,
            unrealized_pnl=100.0,
            num_positions=2,
        )
        assert pnl.equity == 10500.0
        assert pnl.realized_pnl == 500.0
        assert pnl.unrealized_pnl == 100.0
        assert pnl.num_positions == 2
        assert pnl.timestamp is not None

    def test_pnl_to_redis_dict(self):
        """PnL converts to Redis dict with string values"""
        pnl = PRDPnLUpdate(
            equity=10500.0,
            realized_pnl=500.0,
        )
        redis_dict = pnl.to_redis_dict()

        assert all(isinstance(v, str) for v in redis_dict.values())
        assert "equity" in redis_dict
        assert "timestamp" in redis_dict


class TestEvent:
    """Tests for PRD-001 event schema."""

    def test_event_has_required_fields(self):
        """PRD-001: Event has all required fields"""
        event = PRDEvent(
            event_type="SIGNAL_PUBLISHED",
            source="test",
            message="Test event",
        )
        assert event.event_id is not None
        assert event.timestamp is not None
        assert event.event_type == "SIGNAL_PUBLISHED"
        assert event.source == "test"
        assert event.severity == "INFO"  # Default

    def test_event_severity_values(self):
        """PRD-001: Event severity must be valid"""
        for severity in ["INFO", "WARN", "ERROR", "CRITICAL"]:
            event = PRDEvent(
                event_type="TEST",
                source="test",
                message="Test",
                severity=severity,
            )
            assert event.severity == severity

    def test_event_to_redis_dict(self):
        """Event converts to Redis dict with string values"""
        event = PRDEvent(
            event_type="TEST",
            source="test",
            message="Test message",
            data={"key": "value"},
        )
        redis_dict = event.to_redis_dict()

        assert all(isinstance(v, str) for v in redis_dict.values())
        assert "event_type" in redis_dict
        assert "data" in redis_dict


class TestPublisherConfiguration:
    """Tests for PRD publisher configuration."""

    def test_publisher_default_mode(self):
        """Publisher defaults to paper mode for safety"""
        import os
        # Clear ENGINE_MODE if set
        engine_mode = os.environ.pop("ENGINE_MODE", None)

        try:
            publisher = PRDPublisher()
            assert publisher.mode == "paper"
        finally:
            # Restore
            if engine_mode:
                os.environ["ENGINE_MODE"] = engine_mode

    def test_publisher_stream_maxlen(self):
        """PRD-001: Stream MAXLEN is 10,000"""
        assert PRDPublisher.STREAM_MAXLEN == 10000

    def test_publisher_retry_attempts(self):
        """PRD-001: 3 retry attempts with backoff"""
        assert PRDPublisher.RETRY_ATTEMPTS == 3


# =============================================================================
# SCHEMA DRIFT DETECTION TESTS
# =============================================================================

class TestSchemaNoUnexpectedFields:
    """Tests to ensure no schema drift from PRD-001."""

    def test_prd_signal_no_legacy_fields(self):
        """Ensure PRD signal doesn't have legacy field names"""
        signal = create_prd_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
        )
        redis_dict = signal.to_redis_dict()

        # These are LEGACY field names that should NOT be present
        legacy_fields = [
            "id",           # Should be signal_id
            "ts",           # Should be timestamp (ISO8601)
            "ts_ms",        # Should be timestamp (ISO8601)
            "entry",        # Should be entry_price
            "sl",           # Should be stop_loss
            "tp",           # Should be take_profit
            "mode",         # Not in PRD signal schema
        ]

        for field in legacy_fields:
            assert field not in redis_dict, f"Legacy field '{field}' found in PRD signal"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
