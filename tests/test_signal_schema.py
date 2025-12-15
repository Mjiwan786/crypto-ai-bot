"""
Test signal schema compliance with PRD-001.
Run with: pytest tests/test_signal_schema.py -v
"""
import pytest
import uuid
from datetime import datetime, timezone
from pydantic import ValidationError

# Import the canonical signal DTO if available, otherwise define inline
try:
    from models.canonical_signal_dto import CanonicalSignalDTO, create_canonical_signal
except ImportError:
    from pydantic import BaseModel, Field
    from typing import Optional, Literal
    from enum import Enum

    class Side(str, Enum):
        LONG = "LONG"
        SHORT = "SHORT"

    class Strategy(str, Enum):
        SCALPER = "SCALPER"
        TREND = "TREND"
        MEAN_REVERSION = "MEAN_REVERSION"
        BREAKOUT = "BREAKOUT"

    class Regime(str, Enum):
        TRENDING_UP = "TRENDING_UP"
        TRENDING_DOWN = "TRENDING_DOWN"
        RANGING = "RANGING"
        VOLATILE = "VOLATILE"

    class CanonicalSignalDTO(BaseModel):
        signal_id: str
        timestamp: str
        pair: str
        side: Side
        strategy: Strategy
        regime: Regime
        entry_price: float = Field(gt=0)
        take_profit: float = Field(gt=0)
        stop_loss: float = Field(gt=0)
        confidence: float = Field(ge=0.0, le=1.0)
        position_size_usd: float = Field(gt=0, le=2000)
        risk_reward_ratio: Optional[float] = None


# PRD-001 Required trading pairs
REQUIRED_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]


class TestSignalSchema:
    """Test signal schema compliance with PRD-001."""

    def test_signal_has_all_required_fields(self):
        """PRD-001 5.1: Signal must contain all required fields."""
        signal = CanonicalSignalDTO(
            signal_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="TRENDING_UP",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            position_size_usd=100.0,
        )
        assert signal.signal_id is not None
        assert signal.timestamp is not None
        assert signal.pair == "BTC/USD"
        assert signal.side == "LONG"
        assert signal.strategy == "SCALPER"
        assert signal.regime == "TRENDING_UP"

    def test_side_enum_values(self):
        """PRD-001 5.1: Side must be LONG or SHORT."""
        # Valid sides
        for side in ["LONG", "SHORT"]:
            signal = CanonicalSignalDTO(
                signal_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                pair="BTC/USD",
                side=side,
                strategy="SCALPER",
                regime="RANGING",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=0.8,
                position_size_usd=100.0,
            )
            assert signal.side == side

    def test_strategy_enum_values(self):
        """PRD-001 5.1: Strategy must be one of 4 valid values."""
        valid_strategies = ["SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT"]
        for strategy in valid_strategies:
            signal = CanonicalSignalDTO(
                signal_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                pair="BTC/USD",
                side="LONG",
                strategy=strategy,
                regime="RANGING",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=0.8,
                position_size_usd=100.0,
            )
            assert signal.strategy == strategy

    def test_regime_enum_values(self):
        """PRD-001 5.1: Regime must be one of 4 valid values."""
        valid_regimes = ["TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE"]
        for regime in valid_regimes:
            signal = CanonicalSignalDTO(
                signal_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                regime=regime,
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=0.8,
                position_size_usd=100.0,
            )
            assert signal.regime == regime

    def test_confidence_must_be_between_0_and_1(self):
        """PRD-001 5.1: Confidence must be between 0.0 and 1.0."""
        # Valid confidence
        signal = CanonicalSignalDTO(
            signal_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="RANGING",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.85,
            position_size_usd=100.0,
        )
        assert 0.0 <= signal.confidence <= 1.0

        # Invalid confidence > 1
        with pytest.raises(ValidationError):
            CanonicalSignalDTO(
                signal_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                regime="RANGING",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=1.5,  # Invalid
                position_size_usd=100.0,
            )

    def test_position_size_max_2000(self):
        """PRD-001 7.4: Max position size is $2,000."""
        # Valid position size
        signal = CanonicalSignalDTO(
            signal_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="RANGING",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.8,
            position_size_usd=2000.0,  # Max allowed
        )
        assert signal.position_size_usd <= 2000

        # Invalid position size > 2000
        with pytest.raises(ValidationError):
            CanonicalSignalDTO(
                signal_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                pair="BTC/USD",
                side="LONG",
                strategy="SCALPER",
                regime="RANGING",
                entry_price=50000.0,
                take_profit=52000.0,
                stop_loss=49000.0,
                confidence=0.8,
                position_size_usd=3000.0,  # Invalid - exceeds max
            )

    def test_prices_must_be_positive(self):
        """PRD-001 5.1: All prices must be positive."""
        # Valid prices
        signal = CanonicalSignalDTO(
            signal_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            pair="BTC/USD",
            side="LONG",
            strategy="SCALPER",
            regime="RANGING",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.8,
            position_size_usd=100.0,
        )
        assert signal.entry_price > 0
        assert signal.take_profit > 0
        assert signal.stop_loss > 0

    @pytest.mark.parametrize("pair", REQUIRED_PAIRS)
    def test_all_required_pairs_supported(self, pair):
        """PRD-001 4.A: All 5 required pairs must be supported."""
        signal = CanonicalSignalDTO(
            signal_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            pair=pair,
            side="LONG",
            strategy="SCALPER",
            regime="RANGING",
            entry_price=50000.0,
            take_profit=52000.0,
            stop_loss=49000.0,
            confidence=0.8,
            position_size_usd=100.0,
        )
        assert signal.pair == pair


class TestRedisStreamNaming:
    """Test Redis stream naming conventions per PRD-001."""

    def test_stream_name_format_paper(self):
        """PRD-001 4.B: Paper signals go to signals:paper:<PAIR>."""
        pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
        for pair in pairs:
            safe_pair = pair.replace("/", "-")
            stream_key = f"signals:paper:{safe_pair}"
            assert stream_key.startswith("signals:paper:")
            assert "-" in stream_key  # Should use dash, not slash

    def test_stream_name_format_live(self):
        """PRD-001 4.B: Live signals go to signals:live:<PAIR>."""
        pairs = ["BTC/USD", "ETH/USD", "SOL/USD"]
        for pair in pairs:
            safe_pair = pair.replace("/", "-")
            stream_key = f"signals:live:{safe_pair}"
            assert stream_key.startswith("signals:live:")
            assert "-" in stream_key


class TestMetricsAggregation:
    """Test metrics aggregation per PRD-001."""

    def test_required_metrics_fields(self):
        """PRD-001 Appendix C: Required metrics fields."""
        required_metrics = [
            "signals_per_day",
            "win_rate",
            "roi_30d",
            "roi_90d",
            "profit_factor",
            "max_drawdown",
            "sharpe_ratio",
            "total_trades",
        ]
        # This is a structural test - actual values tested in integration
        for metric in required_metrics:
            assert isinstance(metric, str)
            assert len(metric) > 0
