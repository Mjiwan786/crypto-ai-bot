"""
Unit tests for PRD-001 Section 5.1 Pydantic Models

Tests coverage:
- Side, Strategy, Regime, MACDSignal enums
- Indicators model with field validators (rsi_14, atr_14, volume_ratio)
- SignalMetadata model
- TradingSignal model with comprehensive validators
- Price relationship validators for LONG/SHORT signals
- Edge cases and invalid inputs

Author: Crypto AI Bot Team
"""

import pytest
from datetime import datetime
from models.prd_signal_schema import (
    Side,
    Strategy,
    Regime,
    MACDSignal,
    Indicators,
    SignalMetadata,
    TradingSignal
)


class TestEnums:
    """Test enum definitions."""

    def test_side_enum_values(self):
        """Test Side enum values."""
        assert Side.LONG == "LONG"
        assert Side.SHORT == "SHORT"
        assert len(Side) == 2

    def test_strategy_enum_values(self):
        """Test Strategy enum values."""
        assert Strategy.SCALPER == "SCALPER"
        assert Strategy.TREND == "TREND"
        assert Strategy.MEAN_REVERSION == "MEAN_REVERSION"
        assert Strategy.BREAKOUT == "BREAKOUT"
        assert len(Strategy) == 4

    def test_regime_enum_values(self):
        """Test Regime enum values."""
        assert Regime.TRENDING_UP == "TRENDING_UP"
        assert Regime.TRENDING_DOWN == "TRENDING_DOWN"
        assert Regime.RANGING == "RANGING"
        assert Regime.VOLATILE == "VOLATILE"
        assert len(Regime) == 4

    def test_macd_signal_enum_values(self):
        """Test MACDSignal enum values."""
        assert MACDSignal.BULLISH == "BULLISH"
        assert MACDSignal.BEARISH == "BEARISH"
        assert MACDSignal.NEUTRAL == "NEUTRAL"
        assert len(MACDSignal) == 3


class TestIndicatorsModel:
    """Test Indicators model."""

    def test_indicators_valid(self):
        """Test Indicators model with valid data."""
        indicators = Indicators(
            rsi_14=55.5,
            macd_signal=MACDSignal.BULLISH,
            atr_14=100.0,
            volume_ratio=1.5
        )
        assert indicators.rsi_14 == 55.5
        assert indicators.macd_signal == MACDSignal.BULLISH
        assert indicators.atr_14 == 100.0
        assert indicators.volume_ratio == 1.5

    def test_indicators_rsi_at_boundaries(self):
        """Test RSI at boundaries (0 and 100)."""
        # RSI = 0
        indicators_0 = Indicators(
            rsi_14=0.0,
            macd_signal=MACDSignal.NEUTRAL,
            atr_14=50.0,
            volume_ratio=1.0
        )
        assert indicators_0.rsi_14 == 0.0

        # RSI = 100
        indicators_100 = Indicators(
            rsi_14=100.0,
            macd_signal=MACDSignal.NEUTRAL,
            atr_14=50.0,
            volume_ratio=1.0
        )
        assert indicators_100.rsi_14 == 100.0

    def test_indicators_rsi_below_0_fails(self):
        """Test RSI < 0 fails validation."""
        with pytest.raises(ValueError, match="rsi_14 must be in \\[0, 100\\]"):
            Indicators(
                rsi_14=-1.0,
                macd_signal=MACDSignal.NEUTRAL,
                atr_14=50.0,
                volume_ratio=1.0
            )

    def test_indicators_rsi_above_100_fails(self):
        """Test RSI > 100 fails validation."""
        with pytest.raises(ValueError, match="rsi_14 must be in \\[0, 100\\]"):
            Indicators(
                rsi_14=101.0,
                macd_signal=MACDSignal.NEUTRAL,
                atr_14=50.0,
                volume_ratio=1.0
            )

    def test_indicators_atr_zero_fails(self):
        """Test ATR = 0 fails validation."""
        with pytest.raises(ValueError, match="atr_14 must be > 0"):
            Indicators(
                rsi_14=50.0,
                macd_signal=MACDSignal.NEUTRAL,
                atr_14=0.0,
                volume_ratio=1.0
            )

    def test_indicators_atr_negative_fails(self):
        """Test ATR < 0 fails validation."""
        with pytest.raises(ValueError, match="atr_14 must be > 0"):
            Indicators(
                rsi_14=50.0,
                macd_signal=MACDSignal.NEUTRAL,
                atr_14=-10.0,
                volume_ratio=1.0
            )

    def test_indicators_volume_ratio_zero_fails(self):
        """Test volume_ratio = 0 fails validation."""
        with pytest.raises(ValueError, match="volume_ratio must be > 0"):
            Indicators(
                rsi_14=50.0,
                macd_signal=MACDSignal.NEUTRAL,
                atr_14=50.0,
                volume_ratio=0.0
            )

    def test_indicators_volume_ratio_negative_fails(self):
        """Test volume_ratio < 0 fails validation."""
        with pytest.raises(ValueError, match="volume_ratio must be > 0"):
            Indicators(
                rsi_14=50.0,
                macd_signal=MACDSignal.NEUTRAL,
                atr_14=50.0,
                volume_ratio=-1.0
            )


class TestSignalMetadataModel:
    """Test SignalMetadata model."""

    def test_signal_metadata_all_fields(self):
        """Test SignalMetadata with all fields."""
        metadata = SignalMetadata(
            model_version="v1.2.3",
            backtest_sharpe=2.5,
            latency_ms=10.5
        )
        assert metadata.model_version == "v1.2.3"
        assert metadata.backtest_sharpe == 2.5
        assert metadata.latency_ms == 10.5

    def test_signal_metadata_required_only(self):
        """Test SignalMetadata with only required fields."""
        metadata = SignalMetadata(model_version="v1.0.0")
        assert metadata.model_version == "v1.0.0"
        assert metadata.backtest_sharpe is None
        assert metadata.latency_ms is None

    def test_signal_metadata_optional_fields(self):
        """Test SignalMetadata with some optional fields."""
        metadata = SignalMetadata(
            model_version="v2.0.0",
            backtest_sharpe=3.0
        )
        assert metadata.model_version == "v2.0.0"
        assert metadata.backtest_sharpe == 3.0
        assert metadata.latency_ms is None


class TestTradingSignalModel:
    """Test TradingSignal model."""

    def test_trading_signal_valid_long(self):
        """Test TradingSignal with valid LONG signal."""
        indicators = Indicators(
            rsi_14=60.0,
            macd_signal=MACDSignal.BULLISH,
            atr_14=100.0,
            volume_ratio=1.5
        )

        signal = TradingSignal(
            signal_id="test-001",
            timestamp=datetime.now(),
            trading_pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=51000.0,  # > entry_price for LONG
            stop_loss=49500.0,    # < entry_price for LONG
            confidence=0.85,
            position_size_usd=1000.0,
            indicators=indicators
        )

        assert signal.signal_id == "test-001"
        assert signal.side == Side.LONG
        assert signal.entry_price == 50000.0
        assert signal.take_profit == 51000.0
        assert signal.stop_loss == 49500.0

    def test_trading_signal_valid_short(self):
        """Test TradingSignal with valid SHORT signal."""
        indicators = Indicators(
            rsi_14=40.0,
            macd_signal=MACDSignal.BEARISH,
            atr_14=100.0,
            volume_ratio=1.2
        )

        signal = TradingSignal(
            signal_id="test-002",
            timestamp=datetime.now(),
            trading_pair="ETH/USD",
            side=Side.SHORT,
            strategy=Strategy.TREND,
            regime=Regime.TRENDING_DOWN,
            entry_price=3000.0,
            take_profit=2900.0,  # < entry_price for SHORT
            stop_loss=3050.0,    # > entry_price for SHORT
            confidence=0.75,
            position_size_usd=500.0,
            indicators=indicators
        )

        assert signal.signal_id == "test-002"
        assert signal.side == Side.SHORT
        assert signal.entry_price == 3000.0
        assert signal.take_profit == 2900.0
        assert signal.stop_loss == 3050.0

    def test_trading_signal_with_metadata(self):
        """Test TradingSignal with optional metadata."""
        indicators = Indicators(
            rsi_14=55.0,
            macd_signal=MACDSignal.BULLISH,
            atr_14=80.0,
            volume_ratio=1.3
        )

        metadata = SignalMetadata(
            model_version="v1.5.0",
            backtest_sharpe=2.8,
            latency_ms=15.0
        )

        signal = TradingSignal(
            signal_id="test-003",
            timestamp=datetime.now(),
            trading_pair="SOL/USD",
            side=Side.LONG,
            strategy=Strategy.BREAKOUT,
            regime=Regime.VOLATILE,
            entry_price=100.0,
            take_profit=105.0,
            stop_loss=98.0,
            confidence=0.90,
            position_size_usd=800.0,
            indicators=indicators,
            metadata=metadata
        )

        assert signal.metadata is not None
        assert signal.metadata.model_version == "v1.5.0"
        assert signal.metadata.backtest_sharpe == 2.8

    def test_trading_signal_entry_price_zero_fails(self):
        """Test entry_price = 0 fails validation."""
        indicators = Indicators(
            rsi_14=50.0,
            macd_signal=MACDSignal.NEUTRAL,
            atr_14=50.0,
            volume_ratio=1.0
        )

        with pytest.raises(ValueError, match="entry_price must be > 0"):
            TradingSignal(
                signal_id="test-fail",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.RANGING,
                entry_price=0.0,
                take_profit=100.0,
                stop_loss=50.0,
                confidence=0.5,
                position_size_usd=100.0,
                indicators=indicators
            )

    def test_trading_signal_entry_price_negative_fails(self):
        """Test entry_price < 0 fails validation."""
        indicators = Indicators(
            rsi_14=50.0,
            macd_signal=MACDSignal.NEUTRAL,
            atr_14=50.0,
            volume_ratio=1.0
        )

        with pytest.raises(ValueError, match="entry_price must be > 0"):
            TradingSignal(
                signal_id="test-fail",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.RANGING,
                entry_price=-100.0,
                take_profit=100.0,
                stop_loss=50.0,
                confidence=0.5,
                position_size_usd=100.0,
                indicators=indicators
            )

    def test_trading_signal_confidence_below_0_fails(self):
        """Test confidence < 0 fails validation."""
        indicators = Indicators(
            rsi_14=50.0,
            macd_signal=MACDSignal.NEUTRAL,
            atr_14=50.0,
            volume_ratio=1.0
        )

        with pytest.raises(ValueError, match="confidence must be in \\[0, 1\\]"):
            TradingSignal(
                signal_id="test-fail",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.RANGING,
                entry_price=100.0,
                take_profit=110.0,
                stop_loss=95.0,
                confidence=-0.1,
                position_size_usd=100.0,
                indicators=indicators
            )

    def test_trading_signal_confidence_above_1_fails(self):
        """Test confidence > 1 fails validation."""
        indicators = Indicators(
            rsi_14=50.0,
            macd_signal=MACDSignal.NEUTRAL,
            atr_14=50.0,
            volume_ratio=1.0
        )

        with pytest.raises(ValueError, match="confidence must be in \\[0, 1\\]"):
            TradingSignal(
                signal_id="test-fail",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.RANGING,
                entry_price=100.0,
                take_profit=110.0,
                stop_loss=95.0,
                confidence=1.5,
                position_size_usd=100.0,
                indicators=indicators
            )

    def test_trading_signal_position_size_zero_fails(self):
        """Test position_size_usd = 0 fails validation."""
        indicators = Indicators(
            rsi_14=50.0,
            macd_signal=MACDSignal.NEUTRAL,
            atr_14=50.0,
            volume_ratio=1.0
        )

        with pytest.raises(ValueError, match="position_size_usd must be > 0"):
            TradingSignal(
                signal_id="test-fail",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.RANGING,
                entry_price=100.0,
                take_profit=110.0,
                stop_loss=95.0,
                confidence=0.5,
                position_size_usd=0.0,
                indicators=indicators
            )

    def test_trading_signal_position_size_above_2000_fails(self):
        """Test position_size_usd > 2000 fails validation."""
        indicators = Indicators(
            rsi_14=50.0,
            macd_signal=MACDSignal.NEUTRAL,
            atr_14=50.0,
            volume_ratio=1.0
        )

        with pytest.raises(ValueError, match="position_size_usd must be <= 2000"):
            TradingSignal(
                signal_id="test-fail",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.RANGING,
                entry_price=100.0,
                take_profit=110.0,
                stop_loss=95.0,
                confidence=0.5,
                position_size_usd=2001.0,
                indicators=indicators
            )

    def test_trading_signal_invalid_trading_pair_fails(self):
        """Test invalid trading_pair format fails validation."""
        indicators = Indicators(
            rsi_14=50.0,
            macd_signal=MACDSignal.NEUTRAL,
            atr_14=50.0,
            volume_ratio=1.0
        )

        with pytest.raises(ValueError, match="Invalid trading_pair format"):
            TradingSignal(
                signal_id="test-fail",
                timestamp=datetime.now(),
                trading_pair="BTCUSD",  # Missing separator
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.RANGING,
                entry_price=100.0,
                take_profit=110.0,
                stop_loss=95.0,
                confidence=0.5,
                position_size_usd=100.0,
                indicators=indicators
            )


class TestPriceRelationshipValidation:
    """Test price relationship validation for LONG/SHORT signals."""

    def test_long_signal_take_profit_above_entry_valid(self):
        """Test LONG signal with take_profit > entry_price is valid."""
        indicators = Indicators(
            rsi_14=60.0,
            macd_signal=MACDSignal.BULLISH,
            atr_14=100.0,
            volume_ratio=1.5
        )

        signal = TradingSignal(
            signal_id="long-valid",
            timestamp=datetime.now(),
            trading_pair="BTC/USD",
            side=Side.LONG,
            strategy=Strategy.SCALPER,
            regime=Regime.TRENDING_UP,
            entry_price=50000.0,
            take_profit=51000.0,  # > entry_price (valid)
            stop_loss=49500.0,    # < entry_price (valid)
            confidence=0.85,
            position_size_usd=1000.0,
            indicators=indicators
        )

        assert signal.take_profit > signal.entry_price
        assert signal.stop_loss < signal.entry_price

    def test_long_signal_take_profit_below_entry_fails(self):
        """Test LONG signal with take_profit <= entry_price fails."""
        indicators = Indicators(
            rsi_14=60.0,
            macd_signal=MACDSignal.BULLISH,
            atr_14=100.0,
            volume_ratio=1.5
        )

        with pytest.raises(ValueError, match="LONG signal: take_profit .* must be > entry_price"):
            TradingSignal(
                signal_id="long-invalid-tp",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.TRENDING_UP,
                entry_price=50000.0,
                take_profit=49000.0,  # < entry_price (invalid for LONG)
                stop_loss=49500.0,
                confidence=0.85,
                position_size_usd=1000.0,
                indicators=indicators
            )

    def test_long_signal_take_profit_equal_entry_fails(self):
        """Test LONG signal with take_profit = entry_price fails."""
        indicators = Indicators(
            rsi_14=60.0,
            macd_signal=MACDSignal.BULLISH,
            atr_14=100.0,
            volume_ratio=1.5
        )

        with pytest.raises(ValueError, match="LONG signal: take_profit .* must be > entry_price"):
            TradingSignal(
                signal_id="long-invalid-tp-equal",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.TRENDING_UP,
                entry_price=50000.0,
                take_profit=50000.0,  # = entry_price (invalid for LONG)
                stop_loss=49500.0,
                confidence=0.85,
                position_size_usd=1000.0,
                indicators=indicators
            )

    def test_long_signal_stop_loss_above_entry_fails(self):
        """Test LONG signal with stop_loss >= entry_price fails."""
        indicators = Indicators(
            rsi_14=60.0,
            macd_signal=MACDSignal.BULLISH,
            atr_14=100.0,
            volume_ratio=1.5
        )

        with pytest.raises(ValueError, match="LONG signal: stop_loss .* must be < entry_price"):
            TradingSignal(
                signal_id="long-invalid-sl",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.SCALPER,
                regime=Regime.TRENDING_UP,
                entry_price=50000.0,
                take_profit=51000.0,
                stop_loss=50500.0,  # > entry_price (invalid for LONG)
                confidence=0.85,
                position_size_usd=1000.0,
                indicators=indicators
            )

    def test_short_signal_take_profit_below_entry_valid(self):
        """Test SHORT signal with take_profit < entry_price is valid."""
        indicators = Indicators(
            rsi_14=40.0,
            macd_signal=MACDSignal.BEARISH,
            atr_14=100.0,
            volume_ratio=1.2
        )

        signal = TradingSignal(
            signal_id="short-valid",
            timestamp=datetime.now(),
            trading_pair="ETH/USD",
            side=Side.SHORT,
            strategy=Strategy.TREND,
            regime=Regime.TRENDING_DOWN,
            entry_price=3000.0,
            take_profit=2900.0,  # < entry_price (valid for SHORT)
            stop_loss=3050.0,    # > entry_price (valid for SHORT)
            confidence=0.75,
            position_size_usd=500.0,
            indicators=indicators
        )

        assert signal.take_profit < signal.entry_price
        assert signal.stop_loss > signal.entry_price

    def test_short_signal_take_profit_above_entry_fails(self):
        """Test SHORT signal with take_profit >= entry_price fails."""
        indicators = Indicators(
            rsi_14=40.0,
            macd_signal=MACDSignal.BEARISH,
            atr_14=100.0,
            volume_ratio=1.2
        )

        with pytest.raises(ValueError, match="SHORT signal: take_profit .* must be < entry_price"):
            TradingSignal(
                signal_id="short-invalid-tp",
                timestamp=datetime.now(),
                trading_pair="ETH/USD",
                side=Side.SHORT,
                strategy=Strategy.TREND,
                regime=Regime.TRENDING_DOWN,
                entry_price=3000.0,
                take_profit=3100.0,  # > entry_price (invalid for SHORT)
                stop_loss=3050.0,
                confidence=0.75,
                position_size_usd=500.0,
                indicators=indicators
            )

    def test_short_signal_take_profit_equal_entry_fails(self):
        """Test SHORT signal with take_profit = entry_price fails."""
        indicators = Indicators(
            rsi_14=40.0,
            macd_signal=MACDSignal.BEARISH,
            atr_14=100.0,
            volume_ratio=1.2
        )

        with pytest.raises(ValueError, match="SHORT signal: take_profit .* must be < entry_price"):
            TradingSignal(
                signal_id="short-invalid-tp-equal",
                timestamp=datetime.now(),
                trading_pair="ETH/USD",
                side=Side.SHORT,
                strategy=Strategy.TREND,
                regime=Regime.TRENDING_DOWN,
                entry_price=3000.0,
                take_profit=3000.0,  # = entry_price (invalid for SHORT)
                stop_loss=3050.0,
                confidence=0.75,
                position_size_usd=500.0,
                indicators=indicators
            )

    def test_short_signal_stop_loss_below_entry_fails(self):
        """Test SHORT signal with stop_loss <= entry_price fails."""
        indicators = Indicators(
            rsi_14=40.0,
            macd_signal=MACDSignal.BEARISH,
            atr_14=100.0,
            volume_ratio=1.2
        )

        with pytest.raises(ValueError, match="SHORT signal: stop_loss .* must be > entry_price"):
            TradingSignal(
                signal_id="short-invalid-sl",
                timestamp=datetime.now(),
                trading_pair="ETH/USD",
                side=Side.SHORT,
                strategy=Strategy.TREND,
                regime=Regime.TRENDING_DOWN,
                entry_price=3000.0,
                take_profit=2900.0,
                stop_loss=2950.0,  # < entry_price (invalid for SHORT)
                confidence=0.75,
                position_size_usd=500.0,
                indicators=indicators
            )
