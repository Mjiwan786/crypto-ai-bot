"""
Test PRD-001 Signal Schema API Compatibility (Week 2)

Verifies that signals include both PRD-001 canonical fields and
API-compatible aliases for seamless consumption by signals-api.
"""

import pytest
from agents.infrastructure.prd_publisher import (
    PRDSignal,
    PRDIndicators,
    PRDMetadata,
    Side,
    Strategy,
    Regime,
    MACDSignal,
)


class TestPRDSignalAPICompatibility:
    """Test API-compatible field aliases in PRDSignal"""

    def test_signal_includes_prd001_fields(self):
        """Verify PRD-001 canonical fields are present"""
        signal = PRDSignal(
            pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            position_size_usd=100.0,
        )

        redis_dict = signal.to_redis_dict()

        # PRD-001 required fields
        assert "signal_id" in redis_dict
        assert "timestamp" in redis_dict
        assert "pair" in redis_dict
        assert "side" in redis_dict
        assert "strategy" in redis_dict
        assert "regime" in redis_dict
        assert "entry_price" in redis_dict
        assert "take_profit" in redis_dict
        assert "stop_loss" in redis_dict
        assert "confidence" in redis_dict
        assert "position_size_usd" in redis_dict

    def test_signal_includes_api_compatible_fields(self):
        """Verify API-compatible aliases are present (Week 2)"""
        signal = PRDSignal(
            pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            position_size_usd=100.0,
        )

        redis_dict = signal.to_redis_dict()

        # API-compatible fields (PRD-002 expects these)
        assert "id" in redis_dict
        assert "symbol" in redis_dict
        assert "signal_type" in redis_dict
        assert "price" in redis_dict

    def test_api_field_values_match_prd001(self):
        """Verify API aliases have correct values"""
        signal = PRDSignal(
            pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            position_size_usd=100.0,
        )

        redis_dict = signal.to_redis_dict()

        # Verify values match
        assert redis_dict["id"] == redis_dict["signal_id"]
        assert redis_dict["symbol"] == "BTCUSDT"  # API format
        assert redis_dict["signal_type"] == "LONG"
        assert redis_dict["price"] == "50000.0"
        assert redis_dict["entry_price"] == "50000.0"  # Original still present

    def test_symbol_normalization(self):
        """Test pair to symbol conversion for various formats"""
        test_cases = [
            ("BTC/USD", "BTCUSDT"),
            ("ETH/USD", "ETHUSDT"),
            ("SOL/USD", "SOLUSDT"),
            ("BTC-USD", "BTCUSDT"),  # Dash format
            ("ETHUSDT", "ETHUSDT"),  # Already in API format
        ]

        for pair, expected_symbol in test_cases:
            signal = PRDSignal(
                pair=pair,
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.TRENDING_UP,
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=0.85,
                position_size_usd=100.0,
            )

            redis_dict = signal.to_redis_dict()
            assert redis_dict["symbol"] == expected_symbol, f"Failed for pair: {pair}"

    def test_signal_with_indicators_and_metadata(self):
        """Verify nested objects are flattened correctly"""
        signal = PRDSignal(
            pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            position_size_usd=100.0,
            indicators=PRDIndicators(
                rsi_14=58.3,
                macd_signal=MACDSignal.BULLISH,
                atr_14=425.80,
                volume_ratio=1.23,
            ),
            metadata=PRDMetadata(
                model_version="v2.1.0",
                backtest_sharpe=1.85,
                latency_ms=127,
                strategy_tag="Scalper v2",
                mode="paper",
                timeframe="5m",
            ),
        )

        redis_dict = signal.to_redis_dict()

        # Verify indicators are flattened
        assert "indicators_rsi_14" in redis_dict
        assert "indicators_macd_signal" in redis_dict
        assert "indicators_atr_14" in redis_dict
        assert "indicators_volume_ratio" in redis_dict

        # Verify metadata is flattened
        assert "metadata_model_version" in redis_dict
        assert "metadata_backtest_sharpe" in redis_dict
        assert "metadata_latency_ms" in redis_dict
        assert "metadata_strategy_tag" in redis_dict
        assert "metadata_mode" in redis_dict
        assert "metadata_timeframe" in redis_dict

        # Verify UI-friendly metadata values
        assert redis_dict["metadata_strategy_tag"] == "Scalper v2"
        assert redis_dict["metadata_mode"] == "paper"
        assert redis_dict["metadata_timeframe"] == "5m"

    def test_all_ui_required_fields_present(self):
        """Verify all fields needed by UI are present"""
        signal = PRDSignal(
            pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            position_size_usd=100.0,
        )

        redis_dict = signal.to_redis_dict()

        # UI requirements (from Week 2 scope)
        required_fields = [
            "pair",  # Trading pair
            "side",  # LONG/SHORT
            "strategy",  # Strategy name
            "confidence",  # Confidence score
            "entry_price",  # Entry price
            "stop_loss",  # Stop loss
            "take_profit",  # Take profit
            "timestamp",  # Timestamp
        ]

        for field in required_fields:
            assert field in redis_dict, f"Missing UI-required field: {field}"

    def test_short_signal_api_compatibility(self):
        """Verify SHORT signals also have API-compatible fields"""
        signal = PRDSignal(
            pair="ETH/USD",
            side=Side.SHORT,
            strategy=Strategy.TREND,
            regime=Regime.TRENDING_DOWN,
            entry_price=3000.0,
            take_profit=2900.0,  # TP below entry for SHORT
            stop_loss=3100.0,  # SL above entry for SHORT
            confidence=0.72,
            position_size_usd=150.0,
        )

        redis_dict = signal.to_redis_dict()

        # Verify API fields
        assert redis_dict["id"] == redis_dict["signal_id"]
        assert redis_dict["symbol"] == "ETHUSDT"
        assert redis_dict["signal_type"] == "SHORT"
        assert redis_dict["price"] == "3000.0"

    def test_risk_reward_ratio_calculation(self):
        """Verify risk_reward_ratio is calculated correctly"""
        signal = PRDSignal(
            pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=52000.0,  # +2000
            stop_loss=49000.0,  # -1000
            confidence=0.85,
            position_size_usd=100.0,
            # risk_reward_ratio not provided, should be calculated
        )

        # Risk/reward should be calculated: reward (2000) / risk (1000) = 2.0
        assert signal.risk_reward_ratio == 2.0

        redis_dict = signal.to_redis_dict()
        assert "risk_reward_ratio" in redis_dict
        assert redis_dict["risk_reward_ratio"] == "2.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


