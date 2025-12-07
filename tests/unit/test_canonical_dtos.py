"""
Tests for Canonical Signal and PnL DTOs - Week 2 Task A

Verifies that canonical DTOs:
1. Include all PRD-001, PRD-002, and PRD-003 required fields
2. Generate correct Redis payloads
3. Validate field constraints
4. Calculate derived fields correctly
"""

import pytest
from models.canonical_signal_dto import (
    CanonicalSignalDTO,
    Side,
    Strategy,
    Regime,
    MACDSignal,
    create_canonical_signal,
)
from models.canonical_pnl_dto import (
    CanonicalPnLDTO,
    create_canonical_pnl,
)


class TestCanonicalSignalDTO:
    """Test CanonicalSignalDTO"""

    def test_create_minimal_signal(self):
        """Test creating signal with minimal required fields"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
        )

        assert signal.pair == "BTC/USD"
        assert signal.side == Side.LONG
        assert signal.strategy == Strategy.SCALPER
        assert signal.entry_price == 50000.0
        assert signal.confidence == 0.85
        assert signal.mode == "paper"
        assert signal.risk_reward_ratio == 2.0  # (52000-50000) / (50000-49000) = 2.0

    def test_redis_payload_includes_prd001_fields(self):
        """Verify Redis payload includes all PRD-001 canonical fields"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
        )

        payload = signal.to_redis_payload()

        # PRD-001 required fields (string keys, bytes values)
        assert "signal_id" in payload
        assert "timestamp" in payload
        assert "pair" in payload
        assert "side" in payload
        assert "strategy" in payload
        assert "regime" in payload
        assert "entry_price" in payload
        assert "take_profit" in payload
        assert "stop_loss" in payload
        assert "confidence" in payload
        assert "position_size_usd" in payload
        assert "risk_reward_ratio" in payload

    def test_redis_payload_includes_api_aliases(self):
        """Verify Redis payload includes PRD-002 API-compatible aliases"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
        )

        payload = signal.to_redis_payload()

        # PRD-002 API-compatible fields
        assert "id" in payload
        assert "symbol" in payload
        assert "signal_type" in payload
        assert "price" in payload

        # Verify values match
        assert payload["id"] == payload["signal_id"]
        assert payload["symbol"] == b"BTCUSDT"
        assert payload["signal_type"] == b"LONG"
        assert payload["price"] == b"50000.0"

    def test_redis_payload_includes_ui_fields(self):
        """Verify Redis payload includes PRD-003 UI-friendly fields"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
            timeframe="5m",
            strategy_label="Scalper v2",
        )

        payload = signal.to_redis_payload()

        # PRD-003 UI-friendly fields
        assert "strategy_label" in payload
        assert "timeframe" in payload
        assert "mode" in payload

        assert payload["strategy_label"] == b"Scalper v2"
        assert payload["timeframe"] == b"5m"
        assert payload["mode"] == b"paper"

    def test_auto_generate_strategy_label(self):
        """Verify strategy_label is auto-generated if not provided"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
        )

        assert signal.strategy_label == "Scalper"

    def test_symbol_normalization(self):
        """Test pair to symbol conversion for API compatibility"""
        test_cases = [
            ("BTC/USD", "BTCUSDT"),
            ("ETH/USD", "ETHUSDT"),
            ("SOL/USD", "SOLUSDT"),
            ("BTC-USD", "BTCUSDT"),  # Dash format
        ]

        for pair, expected_symbol in test_cases:
            signal = create_canonical_signal(
                pair=pair,
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=0.85,
                mode="paper",
            )

            payload = signal.to_redis_payload()
            assert payload["symbol"] == expected_symbol.encode(), f"Failed for pair: {pair}"

    def test_short_signal_validation(self):
        """Verify SHORT signal price validation"""
        signal = create_canonical_signal(
            pair="ETH/USD",
            side="SHORT",
            strategy="TREND",
            entry_price=3000.0,
            take_profit=2900.0,  # TP below entry for SHORT
            stop_loss=3100.0,  # SL above entry for SHORT
            confidence=0.72,
            mode="paper",
        )

        assert signal.side == Side.SHORT
        assert signal.risk_reward_ratio == 1.0  # (3000-2900) / (3100-3000) = 1.0

    def test_invalid_long_signal_raises_error(self):
        """Verify invalid LONG signal raises validation error"""
        with pytest.raises(ValueError, match="take_profit.*must be > entry_price"):
            create_canonical_signal(
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                entry_price=50000.0,
                take_profit=48000.0,  # Invalid: TP < entry for LONG
                stop_loss=49000.0,
                confidence=0.85,
                mode="paper",
            )

    def test_invalid_short_signal_raises_error(self):
        """Verify invalid SHORT signal raises validation error"""
        with pytest.raises(ValueError, match="take_profit.*must be < entry_price"):
            create_canonical_signal(
                pair="ETH/USD",
                side="SHORT",
                strategy="TREND",
                entry_price=3000.0,
                take_profit=3100.0,  # Invalid: TP > entry for SHORT
                stop_loss=2900.0,
                confidence=0.72,
                mode="paper",
            )

    def test_indicators_included_in_payload(self):
        """Verify optional indicators are included in payload when provided"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
            rsi_14=58.3,
            macd_signal="BULLISH",
            atr_14=425.80,
            volume_ratio=1.23,
        )

        payload = signal.to_redis_payload()

        assert "rsi_14" in payload
        assert "macd_signal" in payload
        assert "atr_14" in payload
        assert "volume_ratio" in payload

        assert payload["rsi_14"] == b"58.3"
        assert payload["macd_signal"] == b"BULLISH"
        assert payload["atr_14"] == b"425.8"
        assert payload["volume_ratio"] == b"1.23"

    def test_metadata_included_in_payload(self):
        """Verify optional metadata is included in payload when provided"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
            model_version="v2.1.0",
            backtest_sharpe=1.85,
            latency_ms=127,
        )

        payload = signal.to_redis_payload()

        assert "model_version" in payload
        assert "backtest_sharpe" in payload
        assert "latency_ms" in payload

        assert payload["model_version"] == b"v2.1.0"
        assert payload["backtest_sharpe"] == b"1.85"
        assert payload["latency_ms"] == b"127"

    def test_stream_key_generation(self):
        """Verify stream key generation matches PRD-001"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
        )

        assert signal.get_stream_key("paper") == "signals:paper:BTC-USD"
        assert signal.get_stream_key("live") == "signals:live:BTC-USD"
        assert signal.get_stream_key() == "signals:paper:BTC-USD"  # Uses self.mode

    def test_all_ui_required_fields_present(self):
        """Verify all fields needed by UI are present"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
            timeframe="5m",
        )

        payload = signal.to_redis_payload()

        # UI requirements (from PRD-003)
        required_fields = [
            "pair",  # Trading pair
            "side",  # LONG/SHORT
            "strategy",  # Strategy name
            "confidence",  # Confidence score
            "entry_price",  # Entry price
            "stop_loss",  # Stop loss
            "take_profit",  # Take profit
            "timestamp",  # Timestamp
            "timeframe",  # Timeframe (UI filtering)
            "mode",  # Paper/live (UI display)
        ]

        for field in required_fields:
            assert field in payload, f"Missing UI-required field: {field}"


class TestCanonicalPnLDTO:
    """Test CanonicalPnLDTO"""

    def test_create_minimal_pnl(self):
        """Test creating PnL with minimal required fields"""
        pnl = create_canonical_pnl(
            equity=10500.0,
            realized_pnl=500.0,
            unrealized_pnl=100.0,
            num_positions=2,
            mode="paper",
        )

        assert pnl.equity == 10500.0
        assert pnl.realized_pnl == 500.0
        assert pnl.unrealized_pnl == 100.0
        assert pnl.num_positions == 2
        assert pnl.mode == "paper"
        assert pnl.total_pnl == 600.0  # Auto-calculated

    def test_redis_payload_includes_prd001_fields(self):
        """Verify Redis payload includes all PRD-001 canonical fields"""
        pnl = create_canonical_pnl(
            equity=10500.0,
            realized_pnl=500.0,
            unrealized_pnl=100.0,
            num_positions=2,
            drawdown_pct=2.5,
            mode="paper",
        )

        payload = pnl.to_redis_payload()

        # PRD-001 required fields
        assert "timestamp" in payload
        assert "equity" in payload
        assert "realized_pnl" in payload
        assert "unrealized_pnl" in payload
        assert "num_positions" in payload
        assert "drawdown_pct" in payload

    def test_redis_payload_includes_api_fields(self):
        """Verify Redis payload includes PRD-002 API-compatible fields"""
        pnl = create_canonical_pnl(
            equity=10500.0,
            realized_pnl=500.0,
            unrealized_pnl=100.0,
            num_positions=2,
            mode="paper",
            total_trades=142,
            win_rate=0.64,
        )

        payload = pnl.to_redis_payload()

        # PRD-002 API-compatible fields
        assert "total_pnl" in payload
        assert "total_trades" in payload
        assert "win_rate" in payload

        assert payload["total_pnl"] == b"600.0"
        assert payload["total_trades"] == b"142"
        assert payload["win_rate"] == b"0.64"

    def test_redis_payload_includes_ui_fields(self):
        """Verify Redis payload includes PRD-003 UI-friendly fields"""
        pnl = create_canonical_pnl(
            equity=12500.0,
            realized_pnl=2500.0,
            unrealized_pnl=0.0,
            num_positions=0,
            mode="paper",
            initial_balance=10000.0,
            total_roi=25.0,
            profit_factor=1.85,
            sharpe_ratio=1.92,
            max_drawdown=5.2,
        )

        payload = pnl.to_redis_payload()

        # PRD-003 UI-friendly fields
        assert "total_roi" in payload
        assert "profit_factor" in payload
        assert "sharpe_ratio" in payload
        assert "max_drawdown" in payload
        assert "mode" in payload
        assert "initial_balance" in payload

        assert payload["total_roi"] == b"25.0"
        assert payload["profit_factor"] == b"1.85"
        assert payload["sharpe_ratio"] == b"1.92"
        assert payload["max_drawdown"] == b"5.2"

    def test_auto_calculate_total_pnl(self):
        """Verify total_pnl is auto-calculated if not provided"""
        pnl = create_canonical_pnl(
            equity=10500.0,
            realized_pnl=500.0,
            unrealized_pnl=100.0,
            num_positions=2,
            mode="paper",
        )

        assert pnl.total_pnl == 600.0  # realized + unrealized

    def test_auto_calculate_total_roi(self):
        """Verify total_roi is auto-calculated if initial_balance provided"""
        pnl = create_canonical_pnl(
            equity=12500.0,
            realized_pnl=2500.0,
            unrealized_pnl=0.0,
            num_positions=0,
            mode="paper",
            initial_balance=10000.0,
        )

        assert pnl.total_roi == 25.0  # ((12500 - 10000) / 10000) * 100

    def test_auto_calculate_max_drawdown(self):
        """Verify max_drawdown defaults to abs(drawdown_pct) if not provided"""
        pnl = create_canonical_pnl(
            equity=9500.0,
            realized_pnl=-500.0,
            unrealized_pnl=0.0,
            num_positions=0,
            mode="paper",
            drawdown_pct=-5.0,
        )

        assert pnl.max_drawdown == 5.0  # abs(-5.0)

    def test_stream_key_generation(self):
        """Verify stream key generation matches PRD-001"""
        pnl = create_canonical_pnl(
            equity=10500.0,
            realized_pnl=500.0,
            unrealized_pnl=100.0,
            num_positions=2,
            mode="paper",
        )

        assert pnl.get_stream_key("paper") == "pnl:paper:equity_curve"
        assert pnl.get_stream_key("live") == "pnl:live:equity_curve"
        assert pnl.get_stream_key() == "pnl:paper:equity_curve"  # Uses self.mode

    def test_all_ui_required_fields_present(self):
        """Verify all fields needed by UI are present"""
        pnl = create_canonical_pnl(
            equity=12500.0,
            realized_pnl=2500.0,
            unrealized_pnl=0.0,
            num_positions=0,
            mode="paper",
            initial_balance=10000.0,
            total_trades=142,
            win_rate=0.64,
            total_roi=25.0,
            profit_factor=1.85,
            sharpe_ratio=1.92,
            max_drawdown=5.2,
        )

        payload = pnl.to_redis_payload()

        # UI requirements (from PRD-003)
        required_fields = [
            "equity",  # Current equity
            "total_pnl",  # Total PnL
            "total_roi",  # Total ROI %
            "win_rate",  # Win rate
            "profit_factor",  # Profit factor
            "sharpe_ratio",  # Sharpe ratio
            "max_drawdown",  # Max drawdown %
            "timestamp",  # Timestamp
            "mode",  # Paper/live (UI display)
        ]

        for field in required_fields:
            assert field in payload, f"Missing UI-required field: {field}"


class TestCanonicalDTOsIntegration:
    """Integration tests for canonical DTOs"""

    def test_signal_payload_shape_matches_api_expectations(self):
        """Verify signal payload shape matches what signals-api expects"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
            timeframe="5m",
        )

        payload = signal.to_redis_payload()

        # API expects these fields (PRD-002)
        assert "id" in payload
        assert "symbol" in payload
        assert "signal_type" in payload
        assert "price" in payload
        assert "timestamp" in payload
        assert "confidence" in payload
        assert "stop_loss" in payload
        assert "take_profit" in payload

    def test_pnl_payload_shape_matches_api_expectations(self):
        """Verify PnL payload shape matches what signals-api expects"""
        pnl = create_canonical_pnl(
            equity=12500.0,
            realized_pnl=2500.0,
            unrealized_pnl=0.0,
            num_positions=0,
            mode="paper",
            total_trades=142,
            win_rate=0.64,
        )

        payload = pnl.to_redis_payload()

        # API expects these fields (PRD-002)
        assert "timestamp" in payload
        assert "equity" in payload
        assert "total_pnl" in payload
        assert "total_trades" in payload
        assert "win_rate" in payload

    def test_signal_payload_all_values_are_bytes(self):
        """Verify all payload values are bytes (Redis XADD requirement)"""
        signal = create_canonical_signal(
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            mode="paper",
        )

        payload = signal.to_redis_payload()

        # All values must be bytes, keys are strings
        for key, value in payload.items():
            assert isinstance(key, str), f"Key {key} should be string"
            assert isinstance(value, bytes), f"Value for {key} should be bytes"

    def test_pnl_payload_all_values_are_bytes(self):
        """Verify all payload values are bytes (Redis XADD requirement)"""
        pnl = create_canonical_pnl(
            equity=10500.0,
            realized_pnl=500.0,
            unrealized_pnl=100.0,
            num_positions=2,
            mode="paper",
        )

        payload = pnl.to_redis_payload()

        # All values must be bytes, keys are strings
        for key, value in payload.items():
            assert isinstance(key, str), f"Key {key} should be string"
            assert isinstance(value, bytes), f"Value for {key} should be bytes"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

