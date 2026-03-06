"""
Unit tests for market data module.

Tests:
- Pair normalization (internal_to_stream, stream_to_internal)
- Outlier filter behavior
- Config loading
- TickerData/SyntheticPrice data classes
"""

import pytest
from unittest.mock import MagicMock

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


class TestPairNormalization:
    """Tests for pair format conversion."""

    def test_internal_to_stream(self):
        """BTC/USD -> BTC-USD"""
        from market_data.base import internal_to_stream

        assert internal_to_stream("BTC/USD") == "BTC-USD"
        assert internal_to_stream("ETH/USD") == "ETH-USD"
        assert internal_to_stream("SOL/USD") == "SOL-USD"

    def test_stream_to_internal(self):
        """BTC-USD -> BTC/USD"""
        from market_data.base import stream_to_internal

        assert stream_to_internal("BTC-USD") == "BTC/USD"
        assert stream_to_internal("ETH-USD") == "ETH/USD"
        assert stream_to_internal("SOL-USD") == "SOL/USD"

    def test_roundtrip_conversion(self):
        """Test internal -> stream -> internal roundtrip."""
        from market_data.base import internal_to_stream, stream_to_internal

        pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD"]

        for pair in pairs:
            stream = internal_to_stream(pair)
            back = stream_to_internal(stream)
            assert back == pair, f"Roundtrip failed for {pair}"

    def test_kraken_symbol_map(self):
        """Test Kraken-specific symbol mapping."""
        from market_data.kraken_feed import KrakenFeed

        feed = KrakenFeed.__new__(KrakenFeed)
        feed._symbol_map = {"BTC/USD": "XBT/USD"}
        feed._symbol_reverse = {"XBT/USD": "BTC/USD"}

        assert feed.normalize_pair("BTC/USD") == "XBT/USD"
        assert feed.denormalize_pair("XBT/USD") == "BTC/USD"

    def test_binance_symbol_map(self):
        """Test Binance-specific symbol mapping."""
        from market_data.binance_feed import BinanceFeed

        feed = BinanceFeed.__new__(BinanceFeed)
        feed._symbol_map = {"BTC/USD": "BTC/USDT"}
        feed._symbol_reverse = {"BTC/USDT": "BTC/USD"}

        assert feed.normalize_pair("BTC/USD") == "BTC/USDT"
        assert feed.denormalize_pair("BTC/USDT") == "BTC/USD"


class TestOutlierFilter:
    """Tests for outlier filtering in price engine."""

    def test_outlier_detection(self):
        """Test that outliers are correctly identified and filtered."""
        from market_data.price_engine import PriceEngine
        from market_data.base import TickerData
        from market_data.config import MarketDataConfig

        # Create mock config
        config = MarketDataConfig(
            outlier_filter={
                "enabled": True,
                "max_deviation_pct": 1.5,
                "min_exchanges_for_filter": 2,
            }
        )

        # Create engine with mock orchestrator
        mock_orchestrator = MagicMock()
        mock_orchestrator.config = config
        engine = PriceEngine(mock_orchestrator, config)

        # Create tickers with one outlier
        tickers = {
            "kraken": TickerData(
                ts_ms=1000000,
                exchange="kraken",
                pair="BTC/USD",
                price=50000.0,  # Normal price
            ),
            "binance": TickerData(
                ts_ms=1000000,
                exchange="binance",
                pair="BTC/USD",
                price=50100.0,  # Normal price (0.2% deviation)
            ),
            "outlier_exchange": TickerData(
                ts_ms=1000000,
                exchange="outlier",
                pair="BTC/USD",
                price=55000.0,  # Outlier (10% deviation)
            ),
        }

        # Filter outliers
        filtered = engine._filter_outliers(tickers)

        # Outlier should be removed
        assert "kraken" in filtered
        assert "binance" in filtered
        assert "outlier_exchange" not in filtered

    def test_no_filter_when_below_min_exchanges(self):
        """Test that filter is not applied with fewer than min exchanges."""
        from market_data.price_engine import PriceEngine
        from market_data.base import TickerData
        from market_data.config import MarketDataConfig

        config = MarketDataConfig(
            outlier_filter={
                "enabled": True,
                "max_deviation_pct": 1.5,
                "min_exchanges_for_filter": 3,  # Need 3 exchanges
            }
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.config = config
        engine = PriceEngine(mock_orchestrator, config)

        # Only 2 exchanges - filter should not apply
        tickers = {
            "kraken": TickerData(
                ts_ms=1000000,
                exchange="kraken",
                pair="BTC/USD",
                price=50000.0,
            ),
            "binance": TickerData(
                ts_ms=1000000,
                exchange="binance",
                pair="BTC/USD",
                price=55000.0,  # 10% deviation but should not be filtered
            ),
        }

        filtered = engine._filter_outliers(tickers)

        # All tickers should remain
        assert len(filtered) == 2

    def test_all_prices_valid(self):
        """Test that all prices pass when within threshold."""
        from market_data.price_engine import PriceEngine
        from market_data.base import TickerData
        from market_data.config import MarketDataConfig

        config = MarketDataConfig(
            outlier_filter={
                "enabled": True,
                "max_deviation_pct": 2.0,
                "min_exchanges_for_filter": 2,
            }
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.config = config
        engine = PriceEngine(mock_orchestrator, config)

        # All prices within 2% of median
        tickers = {
            "kraken": TickerData(
                ts_ms=1000000,
                exchange="kraken",
                pair="BTC/USD",
                price=50000.0,
            ),
            "binance": TickerData(
                ts_ms=1000000,
                exchange="binance",
                pair="BTC/USD",
                price=50500.0,  # 1% deviation
            ),
            "coinbase": TickerData(
                ts_ms=1000000,
                exchange="coinbase",
                pair="BTC/USD",
                price=49800.0,  # 0.4% deviation
            ),
        }

        filtered = engine._filter_outliers(tickers)

        # All should pass
        assert len(filtered) == 3


class TestTickerData:
    """Tests for TickerData data class."""

    def test_ticker_creation(self):
        """Test TickerData instantiation."""
        from market_data.base import TickerData

        ticker = TickerData(
            ts_ms=1700000000000,
            exchange="kraken",
            pair="BTC/USD",
            price=50000.0,
            bid=49990.0,
            ask=50010.0,
            volume=1000000.0,
            latency_ms=50,
            source="rest",
        )

        assert ticker.ts_ms == 1700000000000
        assert ticker.exchange == "kraken"
        assert ticker.pair == "BTC/USD"
        assert ticker.price == 50000.0
        assert ticker.bid == 49990.0
        assert ticker.ask == 50010.0

    def test_ticker_spread(self):
        """Test spread calculation."""
        from market_data.base import TickerData

        ticker = TickerData(
            ts_ms=1000,
            exchange="test",
            pair="BTC/USD",
            price=50000.0,
            bid=49990.0,
            ask=50010.0,
        )

        assert ticker.spread == 20.0  # 50010 - 49990

    def test_ticker_spread_pct(self):
        """Test spread percentage calculation."""
        from market_data.base import TickerData

        ticker = TickerData(
            ts_ms=1000,
            exchange="test",
            pair="BTC/USD",
            price=50000.0,
            bid=49990.0,
            ask=50010.0,
        )

        # Spread: 20, Mid: 50000, Spread %: 0.04%
        assert ticker.spread_pct is not None
        assert abs(ticker.spread_pct - 0.04) < 0.01

    def test_ticker_to_dict(self):
        """Test Redis-compatible dict conversion."""
        from market_data.base import TickerData

        ticker = TickerData(
            ts_ms=1000,
            exchange="kraken",
            pair="BTC/USD",
            price=50000.0,
        )

        d = ticker.to_dict()

        assert d["ts_ms"] == "1000"
        assert d["exchange"] == "kraken"
        assert d["pair"] == "BTC/USD"
        assert d["price"] == "50000.0"

    def test_ticker_from_dict(self):
        """Test creation from Redis dict."""
        from market_data.base import TickerData

        d = {
            "ts_ms": "1000",
            "exchange": "kraken",
            "pair": "BTC/USD",
            "price": "50000.0",
            "bid": "49990.0",
            "ask": "50010.0",
            "volume": "",
            "latency_ms": "50",
            "source": "rest",
        }

        ticker = TickerData.from_dict(d)

        assert ticker.ts_ms == 1000
        assert ticker.price == 50000.0
        assert ticker.bid == 49990.0
        assert ticker.volume is None  # Empty string -> None


class TestSyntheticPrice:
    """Tests for SyntheticPrice data class."""

    def test_synthetic_price_creation(self):
        """Test SyntheticPrice instantiation."""
        from market_data.price_engine import SyntheticPrice

        price = SyntheticPrice(
            ts_ms=1700000000000,
            pair="BTC/USD",
            price=50050.0,
            exchanges_used=["kraken", "binance"],
            weights_used={"kraken": 0.4, "binance": 0.6},
            spread=20.0,
            confidence=0.8,
            stale_exchanges=[],
        )

        assert price.pair == "BTC/USD"
        assert price.price == 50050.0
        assert len(price.exchanges_used) == 2
        assert price.confidence == 0.8

    def test_synthetic_price_to_dict(self):
        """Test Redis-compatible dict conversion."""
        from market_data.price_engine import SyntheticPrice

        price = SyntheticPrice(
            ts_ms=1000,
            pair="BTC/USD",
            price=50000.0,
            exchanges_used=["kraken", "binance"],
            weights_used={"kraken": 0.4, "binance": 0.6},
            confidence=0.8,
        )

        d = price.to_dict()

        assert d["pair"] == "BTC/USD"
        assert d["price"] == "50000.0"
        assert "kraken" in d["exchanges_used"]
        assert d["confidence"] == "0.8"


class TestWeightedPrice:
    """Tests for weighted price calculation."""

    def test_weighted_average(self):
        """Test weighted average price calculation."""
        from market_data.price_engine import PriceEngine
        from market_data.base import TickerData
        from market_data.config import MarketDataConfig

        config = MarketDataConfig(
            weights={"kraken": 0.4, "binance": 0.6}
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.config = config
        engine = PriceEngine(mock_orchestrator, config)

        tickers = {
            "kraken": TickerData(
                ts_ms=1000,
                exchange="kraken",
                pair="BTC/USD",
                price=50000.0,
            ),
            "binance": TickerData(
                ts_ms=1000,
                exchange="binance",
                pair="BTC/USD",
                price=50100.0,
            ),
        }

        weighted_price, weights = engine._compute_weighted_price(tickers)

        # Expected: 0.4 * 50000 + 0.6 * 50100 = 20000 + 30060 = 50060
        assert abs(weighted_price - 50060.0) < 0.01
        assert abs(weights["kraken"] - 0.4) < 0.01
        assert abs(weights["binance"] - 0.6) < 0.01

    def test_equal_weights_fallback(self):
        """Test equal weights when no weights configured."""
        from market_data.price_engine import PriceEngine
        from market_data.base import TickerData
        from market_data.config import MarketDataConfig

        config = MarketDataConfig(weights={})  # No weights

        mock_orchestrator = MagicMock()
        mock_orchestrator.config = config
        engine = PriceEngine(mock_orchestrator, config)

        tickers = {
            "kraken": TickerData(
                ts_ms=1000,
                exchange="kraken",
                pair="BTC/USD",
                price=50000.0,
            ),
            "binance": TickerData(
                ts_ms=1000,
                exchange="binance",
                pair="BTC/USD",
                price=50100.0,
            ),
        }

        weighted_price, weights = engine._compute_weighted_price(tickers)

        # Equal weights: (50000 + 50100) / 2 = 50050
        assert abs(weighted_price - 50050.0) < 0.01
        assert abs(weights["kraken"] - 0.5) < 0.01
        assert abs(weights["binance"] - 0.5) < 0.01


class TestConfidenceCalculation:
    """Tests for confidence score calculation."""

    def test_full_confidence(self):
        """Test full confidence with all exchanges and spread."""
        from market_data.price_engine import PriceEngine
        from market_data.config import MarketDataConfig

        config = MarketDataConfig(
            enabled_exchanges=["kraken", "binance"],
            confidence={
                "base_confidence": 1.0,
                "penalty_per_missing_exchange": 0.2,
                "penalty_no_spread": 0.2,
                "min_confidence": 0.0,
                "max_confidence": 1.0,
            }
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.config = config
        engine = PriceEngine(mock_orchestrator, config)

        confidence = engine._compute_confidence(
            exchanges_used=["kraken", "binance"],
            total_exchanges=2,
            has_spread=True,
        )

        assert confidence == 1.0

    def test_confidence_missing_exchange(self):
        """Test confidence penalty for missing exchange."""
        from market_data.price_engine import PriceEngine
        from market_data.config import MarketDataConfig

        config = MarketDataConfig(
            enabled_exchanges=["kraken", "binance"],
            confidence={
                "base_confidence": 1.0,
                "penalty_per_missing_exchange": 0.2,
                "penalty_no_spread": 0.2,
                "min_confidence": 0.0,
                "max_confidence": 1.0,
            }
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.config = config
        engine = PriceEngine(mock_orchestrator, config)

        confidence = engine._compute_confidence(
            exchanges_used=["kraken"],  # Only one exchange
            total_exchanges=2,
            has_spread=True,
        )

        # 1.0 - 0.2 (one missing) = 0.8
        assert confidence == 0.8

    def test_confidence_no_spread(self):
        """Test confidence penalty for missing spread."""
        from market_data.price_engine import PriceEngine
        from market_data.config import MarketDataConfig

        config = MarketDataConfig(
            enabled_exchanges=["kraken", "binance"],
            confidence={
                "base_confidence": 1.0,
                "penalty_per_missing_exchange": 0.2,
                "penalty_no_spread": 0.2,
                "min_confidence": 0.0,
                "max_confidence": 1.0,
            }
        )

        mock_orchestrator = MagicMock()
        mock_orchestrator.config = config
        engine = PriceEngine(mock_orchestrator, config)

        confidence = engine._compute_confidence(
            exchanges_used=["kraken", "binance"],
            total_exchanges=2,
            has_spread=False,
        )

        # 1.0 - 0.2 (no spread) = 0.8
        assert confidence == 0.8


class TestConfigLoading:
    """Tests for config loading."""

    def test_default_config(self):
        """Test default config values."""
        from market_data.config import MarketDataConfig

        config = MarketDataConfig()

        assert config.feature_flags.market_data_enabled == True
        assert "kraken" in config.enabled_exchanges
        assert "binance" in config.enabled_exchanges
        assert "BTC/USD" in config.pairs

    def test_config_weights(self):
        """Test weight retrieval."""
        from market_data.config import MarketDataConfig

        config = MarketDataConfig(
            weights={"kraken": 0.3, "binance": 0.7}
        )

        assert config.get_weight("kraken") == 0.3
        assert config.get_weight("binance") == 0.7

    def test_config_symbol_mapping(self):
        """Test exchange-specific symbol mapping."""
        from market_data.config import MarketDataConfig, ExchangeOverrideConfig

        config = MarketDataConfig(
            exchange_overrides={
                "kraken": ExchangeOverrideConfig(
                    symbol_map={"BTC/USD": "XBT/USD"}
                )
            }
        )

        assert config.get_symbol_for_exchange("kraken", "BTC/USD") == "XBT/USD"
        assert config.get_symbol_for_exchange("binance", "BTC/USD") == "BTC/USD"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
