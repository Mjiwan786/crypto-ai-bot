"""
Unit tests for the canonical trading pairs module.

Tests config/trading_pairs.py to ensure:
1. All pairs are correctly defined
2. Helper functions work as expected
3. Kraken normalization maps are consistent
4. Enabled/disabled filtering works
"""

import pytest
from config.trading_pairs import (
    TradingPair,
    LiquidityTier,
    TRADING_PAIRS_CONFIG,
    get_all_pairs,
    get_enabled_pairs,
    get_pair_symbols,
    get_kraken_symbols,
    get_stream_symbols,
    get_pair_by_symbol,
    symbol_to_kraken,
    kraken_to_symbol,
    symbol_to_stream,
    stream_to_symbol,
    get_pairs_by_tier,
    get_pairs_csv,
    is_valid_pair,
    is_enabled_pair,
    validate_pairs_list,
    get_normalize_map,
    get_denormalize_map,
    DEFAULT_TRADING_PAIRS_CSV,
    ENABLED_PAIR_SYMBOLS,
    ALL_PAIR_SYMBOLS,
)


class TestTradingPairConfig:
    """Tests for the canonical trading pairs configuration."""

    def test_all_pairs_loaded(self):
        """Verify all expected pairs are configured."""
        all_pairs = get_all_pairs()
        assert len(all_pairs) == 5, "Should have 5 pairs total (including disabled)"

        symbols = [p.symbol for p in all_pairs]
        assert "BTC/USD" in symbols
        assert "ETH/USD" in symbols
        assert "SOL/USD" in symbols
        assert "LINK/USD" in symbols
        assert "MATIC/USD" in symbols  # Present but disabled

    def test_enabled_pairs(self):
        """Verify only enabled pairs are returned."""
        enabled = get_enabled_pairs()
        assert len(enabled) == 4, "Should have 4 enabled pairs"

        symbols = [p.symbol for p in enabled]
        assert "BTC/USD" in symbols
        assert "ETH/USD" in symbols
        assert "SOL/USD" in symbols
        assert "LINK/USD" in symbols
        assert "MATIC/USD" not in symbols  # Disabled

    def test_matic_disabled(self):
        """Verify MATIC/USD is disabled (not supported on Kraken WS)."""
        matic = get_pair_by_symbol("MATIC/USD")
        assert matic is not None
        assert matic.enabled is False
        assert "Kraken" in (matic.note or "")

    def test_pair_symbols(self):
        """Test get_pair_symbols helper."""
        enabled_symbols = get_pair_symbols(enabled_only=True)
        assert len(enabled_symbols) == 4
        assert "MATIC/USD" not in enabled_symbols

        all_symbols = get_pair_symbols(enabled_only=False)
        assert len(all_symbols) == 5
        assert "MATIC/USD" in all_symbols

    def test_kraken_symbols(self):
        """Test Kraken symbol conversion."""
        kraken_symbols = get_kraken_symbols(enabled_only=True)
        assert "XBTUSD" in kraken_symbols  # BTC/USD -> XBTUSD
        assert "ETHUSD" in kraken_symbols
        assert "SOLUSD" in kraken_symbols
        assert "LINKUSD" in kraken_symbols
        assert "MATICUSD" not in kraken_symbols  # Disabled

    def test_stream_symbols(self):
        """Test Redis stream format conversion."""
        stream_symbols = get_stream_symbols(enabled_only=True)
        assert "BTC-USD" in stream_symbols
        assert "ETH-USD" in stream_symbols
        assert "SOL-USD" in stream_symbols
        assert "LINK-USD" in stream_symbols
        assert "MATIC-USD" not in stream_symbols  # Disabled


class TestSymbolConversion:
    """Tests for symbol format conversion functions."""

    def test_symbol_to_kraken(self):
        """Test standard to Kraken format conversion."""
        assert symbol_to_kraken("BTC/USD") == "XBTUSD"
        assert symbol_to_kraken("ETH/USD") == "ETHUSD"
        assert symbol_to_kraken("SOL/USD") == "SOLUSD"
        assert symbol_to_kraken("LINK/USD") == "LINKUSD"
        assert symbol_to_kraken("MATIC/USD") == "MATICUSD"  # Even disabled pairs convert
        assert symbol_to_kraken("INVALID/PAIR") is None

    def test_kraken_to_symbol(self):
        """Test Kraken to standard format conversion."""
        assert kraken_to_symbol("XBTUSD") == "BTC/USD"
        assert kraken_to_symbol("ETHUSD") == "ETH/USD"
        assert kraken_to_symbol("SOLUSD") == "SOL/USD"
        assert kraken_to_symbol("LINKUSD") == "LINK/USD"
        assert kraken_to_symbol("MATICUSD") == "MATIC/USD"
        assert kraken_to_symbol("INVALIDUSD") is None

    def test_symbol_to_stream(self):
        """Test standard to Redis stream format."""
        assert symbol_to_stream("BTC/USD") == "BTC-USD"
        assert symbol_to_stream("ETH/USD") == "ETH-USD"

    def test_stream_to_symbol(self):
        """Test Redis stream to standard format."""
        assert stream_to_symbol("BTC-USD") == "BTC/USD"
        assert stream_to_symbol("ETH-USD") == "ETH/USD"


class TestPairLookup:
    """Tests for pair lookup functions."""

    def test_get_pair_by_symbol_standard(self):
        """Test lookup by standard format."""
        pair = get_pair_by_symbol("BTC/USD")
        assert pair is not None
        assert pair.symbol == "BTC/USD"
        assert pair.kraken_symbol == "XBTUSD"
        assert pair.name == "Bitcoin"

    def test_get_pair_by_symbol_stream(self):
        """Test lookup by stream format."""
        pair = get_pair_by_symbol("BTC-USD")
        assert pair is not None
        assert pair.symbol == "BTC/USD"

    def test_get_pair_by_symbol_kraken(self):
        """Test lookup by Kraken format."""
        pair = get_pair_by_symbol("XBTUSD")
        assert pair is not None
        assert pair.symbol == "BTC/USD"

    def test_get_pair_by_symbol_invalid(self):
        """Test lookup of invalid pair."""
        pair = get_pair_by_symbol("INVALID/PAIR")
        assert pair is None

    def test_get_pairs_by_tier(self):
        """Test tier-based pair lookup."""
        tier_1 = get_pairs_by_tier(1)
        assert len(tier_1) == 2
        symbols = [p.symbol for p in tier_1]
        assert "BTC/USD" in symbols
        assert "ETH/USD" in symbols

        tier_2 = get_pairs_by_tier(2)
        assert len(tier_2) == 1
        assert tier_2[0].symbol == "SOL/USD"

        tier_3 = get_pairs_by_tier(3, enabled_only=True)
        assert len(tier_3) == 1
        assert tier_3[0].symbol == "LINK/USD"

        tier_3_all = get_pairs_by_tier(3, enabled_only=False)
        assert len(tier_3_all) == 2  # LINK and MATIC


class TestValidation:
    """Tests for validation functions."""

    def test_is_valid_pair(self):
        """Test pair validity check."""
        assert is_valid_pair("BTC/USD") is True
        assert is_valid_pair("XBTUSD") is True  # Kraken format also valid
        assert is_valid_pair("BTC-USD") is True  # Stream format also valid
        assert is_valid_pair("MATIC/USD") is True  # Configured but disabled
        assert is_valid_pair("INVALID/PAIR") is False

    def test_is_enabled_pair(self):
        """Test enabled pair check."""
        assert is_enabled_pair("BTC/USD") is True
        assert is_enabled_pair("ETH/USD") is True
        assert is_enabled_pair("MATIC/USD") is False  # Disabled
        assert is_enabled_pair("INVALID/PAIR") is False

    def test_validate_pairs_list(self):
        """Test list validation."""
        input_list = ["BTC/USD", "INVALID/PAIR", "MATIC/USD", "ETH/USD"]
        valid = validate_pairs_list(input_list)
        assert len(valid) == 2  # Only BTC/USD and ETH/USD (enabled)
        assert "BTC/USD" in valid
        assert "ETH/USD" in valid
        assert "INVALID/PAIR" not in valid
        assert "MATIC/USD" not in valid  # Disabled


class TestConstants:
    """Tests for module constants."""

    def test_default_trading_pairs_csv(self):
        """Test CSV format constant."""
        csv = DEFAULT_TRADING_PAIRS_CSV
        pairs = csv.split(",")
        assert len(pairs) == 4
        assert "BTC/USD" in pairs
        assert "MATIC/USD" not in pairs

    def test_enabled_pair_symbols(self):
        """Test enabled symbols constant."""
        assert len(ENABLED_PAIR_SYMBOLS) == 4
        assert "MATIC/USD" not in ENABLED_PAIR_SYMBOLS

    def test_all_pair_symbols(self):
        """Test all symbols constant."""
        assert len(ALL_PAIR_SYMBOLS) == 5
        assert "MATIC/USD" in ALL_PAIR_SYMBOLS


class TestNormalizationMaps:
    """Tests for Kraken normalization maps."""

    def test_normalize_map(self):
        """Test standard to Kraken map."""
        norm_map = get_normalize_map()
        assert norm_map["BTC/USD"] == "XBTUSD"
        assert norm_map["ETH/USD"] == "ETHUSD"
        assert norm_map["SOL/USD"] == "SOLUSD"
        assert norm_map["LINK/USD"] == "LINKUSD"
        assert norm_map["MATIC/USD"] == "MATICUSD"

    def test_denormalize_map(self):
        """Test Kraken to standard map."""
        denorm_map = get_denormalize_map()
        assert denorm_map["XBTUSD"] == "BTC/USD"
        assert denorm_map["ETHUSD"] == "ETH/USD"
        assert denorm_map["SOLUSD"] == "SOL/USD"
        assert denorm_map["LINKUSD"] == "LINK/USD"
        assert denorm_map["MATICUSD"] == "MATIC/USD"

    def test_maps_are_inverse(self):
        """Verify normalize and denormalize are exact inverses."""
        norm = get_normalize_map()
        denorm = get_denormalize_map()

        for symbol, kraken in norm.items():
            assert denorm.get(kraken) == symbol, f"Inverse mismatch for {symbol}"


class TestTradingPairDataclass:
    """Tests for the TradingPair dataclass."""

    def test_stream_symbol_property(self):
        """Test stream_symbol property."""
        pair = get_pair_by_symbol("BTC/USD")
        assert pair.stream_symbol == "BTC-USD"

    def test_display_property(self):
        """Test display property."""
        pair = get_pair_by_symbol("BTC/USD")
        assert pair.display == "BTC/USD"

    def test_frozen_dataclass(self):
        """Test that TradingPair is immutable."""
        pair = get_pair_by_symbol("BTC/USD")
        with pytest.raises(Exception):  # FrozenInstanceError
            pair.symbol = "CHANGED"


class TestDeduplicationAndFiltering:
    """Tests for deduplication and disabled pair filtering - canonical enforcement."""

    def test_validate_pairs_list_deduplicates(self):
        """Test that validate_pairs_list removes duplicates."""
        # Input with duplicates
        input_list = ["BTC/USD", "ETH/USD", "BTC/USD", "SOL/USD", "ETH/USD"]
        valid = validate_pairs_list(input_list)

        # Should return unique enabled pairs only
        assert len(valid) == 3
        assert valid.count("BTC/USD") == 1
        assert valid.count("ETH/USD") == 1
        assert valid.count("SOL/USD") == 1

    def test_validate_pairs_list_filters_disabled(self):
        """Test that validate_pairs_list filters out disabled pairs."""
        # Input with enabled and disabled pairs
        input_list = ["BTC/USD", "MATIC/USD", "ETH/USD"]
        valid = validate_pairs_list(input_list)

        # Should only return enabled pairs (MATIC is disabled)
        assert "BTC/USD" in valid
        assert "ETH/USD" in valid
        assert "MATIC/USD" not in valid
        assert len(valid) == 2

    def test_validate_pairs_list_filters_invalid(self):
        """Test that validate_pairs_list filters out invalid pairs."""
        input_list = ["BTC/USD", "INVALID/PAIR", "FAKE/USD", "ETH/USD"]
        valid = validate_pairs_list(input_list)

        # Should only return valid configured pairs
        assert "BTC/USD" in valid
        assert "ETH/USD" in valid
        assert "INVALID/PAIR" not in valid
        assert "FAKE/USD" not in valid

    def test_validate_pairs_list_combined(self):
        """Test deduplication + disabled + invalid filtering together."""
        input_list = [
            "BTC/USD",      # Valid, enabled
            "MATIC/USD",    # Valid, disabled
            "ETH/USD",      # Valid, enabled
            "BTC/USD",      # Duplicate
            "INVALID/X",    # Invalid
            "SOL/USD",      # Valid, enabled
            "ETH/USD",      # Duplicate
        ]
        valid = validate_pairs_list(input_list)

        # Should return only unique, valid, enabled pairs
        assert len(valid) == 3
        assert set(valid) == {"BTC/USD", "ETH/USD", "SOL/USD"}


class TestStreamNamingConsistency:
    """Tests for Redis stream naming consistency (BTC-USD format)."""

    def test_stream_symbol_format(self):
        """Test that stream symbols use dash instead of slash."""
        stream_symbols = get_stream_symbols(enabled_only=True)

        for stream_sym in stream_symbols:
            assert "/" not in stream_sym, f"Stream symbol should use dash, not slash: {stream_sym}"
            assert "-" in stream_sym, f"Stream symbol should contain dash: {stream_sym}"

    def test_stream_symbols_are_unique(self):
        """Test that stream symbols are unique (no duplicates)."""
        stream_symbols = get_stream_symbols(enabled_only=True)

        # Check for duplicates
        seen = set()
        for sym in stream_symbols:
            assert sym not in seen, f"Duplicate stream symbol: {sym}"
            seen.add(sym)

    def test_symbol_to_stream_roundtrip(self):
        """Test that symbol <-> stream conversion is reversible."""
        for pair_symbol in ENABLED_PAIR_SYMBOLS:
            stream_sym = symbol_to_stream(pair_symbol)
            back_to_symbol = stream_to_symbol(stream_sym)
            assert back_to_symbol == pair_symbol, f"Roundtrip failed: {pair_symbol} -> {stream_sym} -> {back_to_symbol}"

    def test_stream_naming_matches_canonical(self):
        """Test that stream naming is consistent with canonical config."""
        for symbol in ENABLED_PAIR_SYMBOLS:
            pair = get_pair_by_symbol(symbol)
            assert pair is not None, f"Pair not found: {symbol}"

            # Stream symbol property should match conversion function
            assert pair.stream_symbol == symbol_to_stream(symbol)

            # Format should be BASE-QUOTE
            assert "-" in pair.stream_symbol
            assert "/" not in pair.stream_symbol


class TestEnabledOnlyPublishing:
    """Tests ensuring only enabled pairs are used for publishing."""

    def test_default_trading_pairs_csv_enabled_only(self):
        """Test that DEFAULT_TRADING_PAIRS_CSV only contains enabled pairs."""
        pairs = DEFAULT_TRADING_PAIRS_CSV.split(",")

        for pair in pairs:
            assert is_enabled_pair(pair), f"Disabled pair in default CSV: {pair}"

    def test_enabled_pair_symbols_no_duplicates(self):
        """Test that ENABLED_PAIR_SYMBOLS has no duplicates."""
        seen = set()
        for sym in ENABLED_PAIR_SYMBOLS:
            assert sym not in seen, f"Duplicate in ENABLED_PAIR_SYMBOLS: {sym}"
            seen.add(sym)

    def test_kraken_symbols_match_enabled(self):
        """Test that Kraken symbols correspond to enabled pairs."""
        kraken_symbols = get_kraken_symbols(enabled_only=True)

        # Each Kraken symbol should map back to an enabled pair
        for kraken_sym in kraken_symbols:
            standard = kraken_to_symbol(kraken_sym)
            assert standard is not None, f"Kraken symbol has no mapping: {kraken_sym}"
            assert is_enabled_pair(standard), f"Kraken symbol maps to disabled pair: {kraken_sym} -> {standard}"
