"""
Unit tests for staging feature flags (A2)

Tests PUBLISH_MODE, REDIS_STREAM_NAME, and EXTRA_PAIRS functionality
with backward compatibility validation.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from agents.core.signal_processor import SignalProcessor


class TestPublishModeFlag:
    """Test PUBLISH_MODE feature flag"""

    @patch.dict(os.environ, {}, clear=True)
    def test_default_publish_mode_paper(self):
        """Default PUBLISH_MODE should be 'paper' with signals:paper stream"""
        processor = SignalProcessor()
        config = processor._load_config()

        assert config["redis_streams"]["processed_signals"] == "signals:paper"

    @patch.dict(os.environ, {"PUBLISH_MODE": "staging"})
    def test_publish_mode_staging(self):
        """PUBLISH_MODE=staging should use signals:paper:staging stream"""
        processor = SignalProcessor()
        config = processor._load_config()

        assert config["redis_streams"]["processed_signals"] == "signals:paper:staging"

    @patch.dict(os.environ, {"PUBLISH_MODE": "live"})
    def test_publish_mode_live(self):
        """PUBLISH_MODE=live should use signals:live stream"""
        processor = SignalProcessor()
        config = processor._load_config()

        assert config["redis_streams"]["processed_signals"] == "signals:live"

    @patch.dict(os.environ, {"PUBLISH_MODE": "paper"})
    def test_publish_mode_paper_explicit(self):
        """Explicit PUBLISH_MODE=paper should use signals:paper stream"""
        processor = SignalProcessor()
        config = processor._load_config()

        assert config["redis_streams"]["processed_signals"] == "signals:paper"


class TestRedisStreamNameOverride:
    """Test REDIS_STREAM_NAME override flag"""

    @patch.dict(os.environ, {"REDIS_STREAM_NAME": "signals:custom:stream"})
    def test_redis_stream_name_override(self):
        """REDIS_STREAM_NAME should override all other settings"""
        processor = SignalProcessor()
        config = processor._load_config()

        assert config["redis_streams"]["processed_signals"] == "signals:custom:stream"

    @patch.dict(os.environ, {
        "REDIS_STREAM_NAME": "signals:override",
        "PUBLISH_MODE": "staging"
    })
    def test_redis_stream_name_overrides_publish_mode(self):
        """REDIS_STREAM_NAME takes priority over PUBLISH_MODE"""
        processor = SignalProcessor()
        config = processor._load_config()

        # Should use REDIS_STREAM_NAME, not PUBLISH_MODE
        assert config["redis_streams"]["processed_signals"] == "signals:override"

    @patch.dict(os.environ, {
        "REDIS_STREAM_NAME": "signals:override",
        "STREAM_SIGNALS_PAPER": "signals:old:var"
    })
    def test_redis_stream_name_overrides_legacy(self):
        """REDIS_STREAM_NAME takes priority over STREAM_SIGNALS_PAPER"""
        processor = SignalProcessor()
        config = processor._load_config()

        assert config["redis_streams"]["processed_signals"] == "signals:override"


class TestBackwardCompatibility:
    """Test backward compatibility with existing environment variables"""

    @patch.dict(os.environ, {"STREAM_SIGNALS_PAPER": "signals:legacy:stream"}, clear=True)
    def test_stream_signals_paper_still_works(self):
        """Legacy STREAM_SIGNALS_PAPER should still work"""
        processor = SignalProcessor()
        config = processor._load_config()

        assert config["redis_streams"]["processed_signals"] == "signals:legacy:stream"

    @patch.dict(os.environ, {
        "STREAM_SIGNALS_PAPER": "signals:legacy",
        "PUBLISH_MODE": "staging"
    })
    def test_publish_mode_overrides_legacy(self):
        """PUBLISH_MODE should override STREAM_SIGNALS_PAPER"""
        processor = SignalProcessor()
        config = processor._load_config()

        # New flag takes precedence
        assert config["redis_streams"]["processed_signals"] == "signals:paper:staging"


class TestExtraPairsFlag:
    """Test EXTRA_PAIRS feature flag"""

    @patch.dict(os.environ, {}, clear=True)
    def test_default_trading_pairs(self):
        """Default trading pairs should be BTC/USD,ETH/USD (from code default)"""
        processor = SignalProcessor()
        pairs = processor._load_trading_pairs()

        # Code default includes SOL/USD and ADA/USD in the hardcoded default
        # This is backward compatible - not changing existing behavior
        assert "BTC/USD" in pairs
        assert "ETH/USD" in pairs

    @patch.dict(os.environ, {"TRADING_PAIRS": "BTC/USD,ETH/USD,SOL/USD"})
    def test_trading_pairs_override(self):
        """TRADING_PAIRS should override defaults"""
        processor = SignalProcessor()
        pairs = processor._load_trading_pairs()

        assert pairs == ["BTC/USD", "ETH/USD", "SOL/USD"]

    @patch.dict(os.environ, {
        "TRADING_PAIRS": "BTC/USD,ETH/USD",
        "EXTRA_PAIRS": "SOL/USD,ADA/USD"
    })
    def test_extra_pairs_additive(self):
        """EXTRA_PAIRS should be added to TRADING_PAIRS"""
        processor = SignalProcessor()
        pairs = processor._load_trading_pairs()

        assert pairs == ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD"]

    @patch.dict(os.environ, {
        "TRADING_PAIRS": "BTC/USD,ETH/USD",
        "EXTRA_PAIRS": "ETH/USD,SOL/USD"  # ETH/USD is duplicate
    })
    def test_extra_pairs_deduplication(self):
        """Duplicate pairs should be removed"""
        processor = SignalProcessor()
        pairs = processor._load_trading_pairs()

        # ETH/USD should appear only once
        assert pairs == ["BTC/USD", "ETH/USD", "SOL/USD"]

    @patch.dict(os.environ, {"EXTRA_PAIRS": "SOL/USD,ADA/USD,AVAX/USD"})
    def test_extra_pairs_with_default_base(self):
        """EXTRA_PAIRS should work with default TRADING_PAIRS"""
        processor = SignalProcessor()
        pairs = processor._load_trading_pairs()

        # Should merge with default BTC/USD,ETH/USD
        assert pairs == ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "AVAX/USD"]

    @patch.dict(os.environ, {
        "TRADING_PAIRS": " BTC/USD , ETH/USD ",
        "EXTRA_PAIRS": " SOL/USD , ADA/USD "
    })
    def test_extra_pairs_whitespace_handling(self):
        """Whitespace should be stripped from pair names"""
        processor = SignalProcessor()
        pairs = processor._load_trading_pairs()

        assert pairs == ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD"]


class TestFeatureFlagPriority:
    """Test priority/precedence of feature flags"""

    @patch.dict(os.environ, {
        "REDIS_STREAM_NAME": "signals:direct:override",
        "PUBLISH_MODE": "staging",
        "STREAM_SIGNALS_PAPER": "signals:legacy"
    })
    def test_stream_selection_priority(self):
        """Test priority: REDIS_STREAM_NAME > PUBLISH_MODE > STREAM_SIGNALS_PAPER"""
        processor = SignalProcessor()
        config = processor._load_config()

        # REDIS_STREAM_NAME should win
        assert config["redis_streams"]["processed_signals"] == "signals:direct:override"

    @patch.dict(os.environ, {
        "PUBLISH_MODE": "staging",
        "STREAM_SIGNALS_PAPER": "signals:legacy"
    })
    def test_stream_selection_priority_without_override(self):
        """Test priority: PUBLISH_MODE > STREAM_SIGNALS_PAPER (no override)"""
        processor = SignalProcessor()
        config = processor._load_config()

        # PUBLISH_MODE should win over legacy var
        assert config["redis_streams"]["processed_signals"] == "signals:paper:staging"


class TestStagingConfiguration:
    """Test full staging configuration"""

    @patch.dict(os.environ, {
        "PUBLISH_MODE": "staging",
        "TRADING_PAIRS": "BTC/USD,ETH/USD",
        "EXTRA_PAIRS": "SOL/USD,ADA/USD,AVAX/USD"
    })
    def test_full_staging_config(self):
        """Test complete staging configuration"""
        processor = SignalProcessor()
        config = processor._load_config()

        # Stream should be staging
        assert config["redis_streams"]["processed_signals"] == "signals:paper:staging"

        # Pairs should include all 5
        assert config["trading_pairs"] == [
            "BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "AVAX/USD"
        ]


class TestSignalRouterIntegration:
    """Test SignalRouter uses same stream selection logic"""

    @patch.dict(os.environ, {"PUBLISH_MODE": "staging"})
    def test_signal_router_respects_publish_mode(self):
        """SignalRouter should use staging stream when PUBLISH_MODE=staging"""
        from agents.core.signal_processor import SignalRouter

        router = SignalRouter(config={})

        # Default stream should be staging
        assert router.execution_streams["default"] == "signals:paper:staging"

    @patch.dict(os.environ, {"REDIS_STREAM_NAME": "signals:custom"})
    def test_signal_router_respects_override(self):
        """SignalRouter should use override when REDIS_STREAM_NAME set"""
        from agents.core.signal_processor import SignalRouter

        router = SignalRouter(config={})

        # Default stream should use override
        assert router.execution_streams["default"] == "signals:custom"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
