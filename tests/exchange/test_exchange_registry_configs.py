"""
Tests for exchange YAML configs loaded via ExchangeRegistry.

Verifies all 8 exchange configs load correctly, have valid metadata,
and conform to expected constraints (IDs, statuses, fees, quotes).
"""

from __future__ import annotations

import pytest

from exchange.exchange_registry import ExchangeConfig, ExchangeRegistry


# ---------------------------------------------------------------------------
# All 8 expected exchange IDs (must match signals-api ExchangeId enum)
# ---------------------------------------------------------------------------
ALL_EXCHANGE_IDS = sorted([
    "binance",
    "bitfinex",
    "bybit",
    "coinbase",
    "gateio",
    "kraken",
    "kucoin",
    "okx",
])

USD_EXCHANGES = {"kraken", "coinbase", "bitfinex"}
USDT_EXCHANGES = {"binance", "bybit", "okx", "kucoin", "gateio"}

GEO_RESTRICTED_US = {"binance", "bybit", "okx", "gateio", "bitfinex"}


@pytest.fixture(scope="module")
def registry() -> ExchangeRegistry:
    """Load the real exchange config directory once per module."""
    return ExchangeRegistry()


# ---------------------------------------------------------------------------
# Loading & discovery
# ---------------------------------------------------------------------------

class TestRegistryLoading:
    """All 8 YAML configs load without error."""

    def test_all_eight_exchanges_loaded(self, registry: ExchangeRegistry) -> None:
        loaded = sorted(c.exchange_id for c in registry.list_exchanges())
        assert loaded == ALL_EXCHANGE_IDS, (
            f"Expected {ALL_EXCHANGE_IDS}, got {loaded}"
        )

    def test_each_exchange_queryable(self, registry: ExchangeRegistry) -> None:
        for eid in ALL_EXCHANGE_IDS:
            config = registry.get_config(eid)
            assert isinstance(config, ExchangeConfig)

    def test_is_supported_all_eight(self, registry: ExchangeRegistry) -> None:
        for eid in ALL_EXCHANGE_IDS:
            assert registry.is_supported(eid), f"{eid} not supported"

    def test_unsupported_raises_keyerror(self, registry: ExchangeRegistry) -> None:
        with pytest.raises(KeyError, match="not found"):
            registry.get_config("mt_gox")


# ---------------------------------------------------------------------------
# Exchange IDs
# ---------------------------------------------------------------------------

class TestExchangeIds:
    """IDs must be lowercase and match the expected canonical set."""

    def test_all_ids_lowercase(self, registry: ExchangeRegistry) -> None:
        for config in registry.list_exchanges():
            assert config.exchange_id == config.exchange_id.lower()

    def test_ids_match_expected(self, registry: ExchangeRegistry) -> None:
        ids = {c.exchange_id for c in registry.list_exchanges()}
        assert ids == set(ALL_EXCHANGE_IDS)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class TestExchangeStatus:
    """Only kraken should be live; all others paper_only."""

    def test_kraken_is_live(self, registry: ExchangeRegistry) -> None:
        config = registry.get_config("kraken")
        assert config.status == "live"

    @pytest.mark.parametrize("exchange_id", [
        "binance", "bitfinex", "bybit", "coinbase", "gateio", "kucoin", "okx",
    ])
    def test_non_kraken_paper_only(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        config = registry.get_config(exchange_id)
        assert config.status == "paper_only", (
            f"{exchange_id} should be paper_only, got {config.status}"
        )

    def test_list_live_returns_only_kraken(self, registry: ExchangeRegistry) -> None:
        live = registry.list_exchanges(status="live")
        assert len(live) == 1
        assert live[0].exchange_id == "kraken"

    def test_list_paper_returns_seven(self, registry: ExchangeRegistry) -> None:
        paper = registry.list_exchanges(status="paper_only")
        assert len(paper) == 7


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------

class TestFees:
    """Fee values must be in a reasonable range (5-50 bps)."""

    @pytest.mark.parametrize("exchange_id", ALL_EXCHANGE_IDS)
    def test_maker_fee_in_range(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        config = registry.get_config(exchange_id)
        assert 5 <= config.maker_fee_bps <= 50, (
            f"{exchange_id} maker_fee_bps={config.maker_fee_bps} out of range"
        )

    @pytest.mark.parametrize("exchange_id", ALL_EXCHANGE_IDS)
    def test_taker_fee_in_range(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        config = registry.get_config(exchange_id)
        assert 5 <= config.taker_fee_bps <= 70, (
            f"{exchange_id} taker_fee_bps={config.taker_fee_bps} out of range"
        )

    def test_maker_less_than_or_equal_taker(self, registry: ExchangeRegistry) -> None:
        for config in registry.list_exchanges():
            assert config.maker_fee_bps <= config.taker_fee_bps, (
                f"{config.exchange_id}: maker {config.maker_fee_bps} > taker {config.taker_fee_bps}"
            )

    def test_specific_fee_values(self, registry: ExchangeRegistry) -> None:
        """Spot-check fee values from the task spec."""
        cases = {
            "kraken": (16, 26),
            "binance": (10, 10),
            "bybit": (10, 10),
            "coinbase": (40, 60),
            "bitfinex": (10, 20),
            "kucoin": (10, 10),
            "okx": (8, 10),
            "gateio": (15, 15),
        }
        for eid, (expected_maker, expected_taker) in cases.items():
            config = registry.get_config(eid)
            assert config.maker_fee_bps == expected_maker, (
                f"{eid} maker: expected {expected_maker}, got {config.maker_fee_bps}"
            )
            assert config.taker_fee_bps == expected_taker, (
                f"{eid} taker: expected {expected_taker}, got {config.taker_fee_bps}"
            )


# ---------------------------------------------------------------------------
# Quote assets
# ---------------------------------------------------------------------------

class TestQuoteAssets:
    """USD vs USDT quote asset must match exchange grouping."""

    @pytest.mark.parametrize("exchange_id", sorted(USD_EXCHANGES))
    def test_usd_exchanges(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        config = registry.get_config(exchange_id)
        assert config.default_quote == "USD", (
            f"{exchange_id} should quote USD, got {config.default_quote}"
        )

    @pytest.mark.parametrize("exchange_id", sorted(USDT_EXCHANGES))
    def test_usdt_exchanges(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        config = registry.get_config(exchange_id)
        assert config.default_quote == "USDT", (
            f"{exchange_id} should quote USDT, got {config.default_quote}"
        )


# ---------------------------------------------------------------------------
# Display names
# ---------------------------------------------------------------------------

class TestDisplayNames:
    """Each exchange must have a non-empty display name."""

    @pytest.mark.parametrize("exchange_id", ALL_EXCHANGE_IDS)
    def test_display_name_present(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        config = registry.get_config(exchange_id)
        assert config.display_name, f"{exchange_id} has empty display_name"
        assert len(config.display_name) >= 2

    def test_specific_display_names(self, registry: ExchangeRegistry) -> None:
        expected = {
            "kraken": "Kraken",
            "coinbase": "Coinbase",
            "binance": "Binance",
            "bybit": "Bybit",
            "bitfinex": "Bitfinex",
            "kucoin": "KuCoin",
            "okx": "OKX",
            "gateio": "Gate.io",
        }
        for eid, expected_name in expected.items():
            config = registry.get_config(eid)
            assert config.display_name == expected_name, (
                f"{eid}: expected '{expected_name}', got '{config.display_name}'"
            )


# ---------------------------------------------------------------------------
# Supported pairs
# ---------------------------------------------------------------------------

class TestSupportedPairs:
    """Each exchange must list at least BTC and ETH pairs."""

    @pytest.mark.parametrize("exchange_id", ALL_EXCHANGE_IDS)
    def test_has_pairs(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        pairs = registry.get_pairs_for_exchange(exchange_id)
        assert len(pairs) >= 2, f"{exchange_id} has fewer than 2 pairs"

    @pytest.mark.parametrize("exchange_id", ALL_EXCHANGE_IDS)
    def test_btc_pair_present(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        pairs = registry.get_pairs_for_exchange(exchange_id)
        btc_pairs = [p for p in pairs if "BTC" in p]
        assert btc_pairs, f"{exchange_id} missing BTC pair"

    @pytest.mark.parametrize("exchange_id", ALL_EXCHANGE_IDS)
    def test_eth_pair_present(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        pairs = registry.get_pairs_for_exchange(exchange_id)
        eth_pairs = [p for p in pairs if "ETH" in p]
        assert eth_pairs, f"{exchange_id} missing ETH pair"


# ---------------------------------------------------------------------------
# Regional restrictions
# ---------------------------------------------------------------------------

class TestRegionalRestrictions:
    """US-restricted exchanges must list US in restrictions."""

    @pytest.mark.parametrize("exchange_id", sorted(GEO_RESTRICTED_US))
    def test_us_restricted(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        assert not registry.is_available_in_region(exchange_id, "US"), (
            f"{exchange_id} should be US-restricted"
        )

    def test_kraken_available_in_us(self, registry: ExchangeRegistry) -> None:
        assert registry.is_available_in_region("kraken", "US")

    def test_coinbase_available_in_us(self, registry: ExchangeRegistry) -> None:
        assert registry.is_available_in_region("coinbase", "US")


# ---------------------------------------------------------------------------
# Raw config structure
# ---------------------------------------------------------------------------

class TestRawConfig:
    """Raw YAML data must be accessible and contain expected keys."""

    @pytest.mark.parametrize("exchange_id", ALL_EXCHANGE_IDS)
    def test_raw_dict_present(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        config = registry.get_config(exchange_id)
        assert isinstance(config.raw, dict)
        assert len(config.raw) > 0

    @pytest.mark.parametrize("exchange_id", ALL_EXCHANGE_IDS)
    def test_raw_has_exchange_section(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        config = registry.get_config(exchange_id)
        assert "exchange" in config.raw, (
            f"{exchange_id} raw config missing 'exchange' section"
        )

    @pytest.mark.parametrize("exchange_id", ALL_EXCHANGE_IDS)
    def test_raw_has_trading_specs(
        self, registry: ExchangeRegistry, exchange_id: str
    ) -> None:
        config = registry.get_config(exchange_id)
        assert "trading_specs" in config.raw, (
            f"{exchange_id} raw config missing 'trading_specs' section"
        )
