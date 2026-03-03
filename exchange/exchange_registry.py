"""
Exchange registry — loads and serves YAML exchange configurations.

Reads exchange config files from ``config/exchange_configs/`` and provides
a clean API for querying exchange metadata, supported pairs, regional
availability, and status.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Default config directory relative to the project root
_DEFAULT_CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "exchange_configs",
)


@dataclass
class ExchangeConfig:
    """Parsed exchange configuration.

    Attributes:
        exchange_id: Canonical lowercase ID (e.g. ``"kraken"``).
        display_name: Human-readable name (e.g. ``"Kraken"``).
        status: Deployment status — ``"live"``, ``"paper_only"``, ``"disabled"``.
        has_testnet: Whether the exchange provides a sandbox / testnet.
        pair_format: Native pair format description (e.g. ``"BASE/QUOTE"``).
        default_quote: Default quote currency (e.g. ``"USD"``, ``"USDT"``).
        min_order_usd: Minimum order value in USD equivalent.
        maker_fee_bps: Maker fee in basis points.
        taker_fee_bps: Taker fee in basis points.
        supported_pairs: List of pairs in internal normalised format.
        regional_restrictions: List of ISO country codes where the exchange
            is **not** available.
        raw: The raw YAML dict for anything not explicitly modelled.
    """

    exchange_id: str
    display_name: str
    status: str = "paper_only"
    has_testnet: bool = False
    pair_format: str = "BASE/QUOTE"
    default_quote: str = "USD"
    min_order_usd: float = 1.0
    maker_fee_bps: float = 0.0
    taker_fee_bps: float = 0.0
    supported_pairs: list[str] = field(default_factory=list)
    regional_restrictions: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class ExchangeRegistry:
    """Registry that discovers and parses exchange YAML configurations.

    Args:
        config_dir: Directory containing ``*.yaml`` exchange configs.
            Defaults to ``config/exchange_configs/`` relative to project root.
    """

    def __init__(self, config_dir: str | None = None) -> None:
        self._config_dir = config_dir or _DEFAULT_CONFIG_DIR
        self._configs: dict[str, ExchangeConfig] = {}
        self._load_all()

    # -- Public API ----------------------------------------------------------

    def get_config(self, exchange_id: str) -> ExchangeConfig:
        """Return the config for *exchange_id*, or raise ``KeyError``."""
        exchange_id = exchange_id.lower()
        if exchange_id not in self._configs:
            raise KeyError(
                f"Exchange '{exchange_id}' not found in registry. "
                f"Available: {sorted(self._configs)}"
            )
        return self._configs[exchange_id]

    def list_exchanges(self, status: str | None = None) -> list[ExchangeConfig]:
        """Return exchange configs, optionally filtered by *status*."""
        configs = list(self._configs.values())
        if status:
            configs = [c for c in configs if c.status == status]
        return sorted(configs, key=lambda c: c.exchange_id)

    def is_supported(self, exchange_id: str) -> bool:
        """Return ``True`` if the exchange has a config in the registry."""
        return exchange_id.lower() in self._configs

    def get_pairs_for_exchange(self, exchange_id: str) -> list[str]:
        """Return the list of supported pairs for *exchange_id*."""
        return list(self.get_config(exchange_id).supported_pairs)

    def is_available_in_region(
        self, exchange_id: str, country_code: str
    ) -> bool:
        """Return ``True`` if the exchange is available in *country_code*."""
        config = self.get_config(exchange_id)
        if not config.regional_restrictions:
            return True
        return country_code.upper() not in [
            r.upper() for r in config.regional_restrictions
        ]

    # -- Internal ------------------------------------------------------------

    def _load_all(self) -> None:
        """Discover and parse all YAML files in the config directory."""
        config_path = Path(self._config_dir)
        if not config_path.is_dir():
            logger.warning(
                "Exchange config directory does not exist: %s", self._config_dir
            )
            return

        for yaml_file in sorted(config_path.glob("*.yaml")):
            try:
                self._load_file(yaml_file)
            except Exception:
                logger.exception("Failed to load exchange config: %s", yaml_file)

    def _load_file(self, path: Path) -> None:
        """Parse a single YAML file and register the exchange."""
        with open(path, "r", encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}

        # Derive exchange_id from filename (e.g. kraken.yaml -> kraken)
        exchange_id = path.stem.lower()

        # Skip non-exchange configs (like kraken_ohlcv.yaml)
        # Heuristic: must have at least an "exchange" or "auth" top-level key,
        # OR be one of the known simple formats (like the original kraken.yaml).
        exchange_section = data.get("exchange", {})
        auth_section = data.get("auth", {})
        symbols_section = data.get("symbols", {})
        trading_section = data.get("trading_specs", {})

        # Build display name
        display_name = (
            exchange_section.get("display_name")
            or exchange_section.get("name", exchange_id).capitalize()
        )

        # Determine status
        # If the config has explicit status, use it; otherwise infer
        status = exchange_section.get("status", "paper_only")
        if exchange_id == "kraken" and "exchange" not in data:
            # Simple legacy kraken.yaml
            status = "live"

        # Testnet
        has_testnet = False
        env_section = exchange_section.get("environment", {})
        endpoints_section = exchange_section.get("endpoints", {})
        if env_section.get("sandbox") or endpoints_section.get("rest", {}).get("sandbox_url"):
            has_testnet = True

        # Pair format
        pair_format = "BASE/QUOTE"
        delim = symbols_section.get("delimiter_stream", "/")
        if delim == "-":
            pair_format = "BASE-QUOTE"
        elif delim == "":
            pair_format = "BASEQUOTE"

        # Default quote
        default_quote = "USD"
        # Binance uses USDT
        denorm = symbols_section.get("denormalize", {})
        if denorm:
            first_internal = next(iter(denorm.values()), "")
            if "/" in first_internal:
                default_quote = first_internal.split("/")[1]

        # Min order USD
        min_order_usd = 1.0
        precision_specs = trading_section.get("precision", {})
        if precision_specs:
            first_spec = next(iter(precision_specs.values()), {})
            if isinstance(first_spec, dict):
                min_notional = first_spec.get("min_notional") or first_spec.get("min_size", 1.0)
                min_order_usd = float(min_notional)

        # Fees
        fees_section = trading_section.get("fees", {})
        maker_fee_bps = float(fees_section.get("maker_bps_default", 0))
        taker_fee_bps = float(fees_section.get("taker_bps_default", 0))

        # For simple kraken.yaml that lacks structured data
        if exchange_id == "kraken" and not fees_section:
            maker_fee_bps = 16.0  # 0.16%
            taker_fee_bps = 26.0  # 0.26%
            min_order_usd = 10.0

        # Supported pairs from symbols.denormalize values
        supported_pairs: list[str] = []
        if denorm:
            supported_pairs = sorted(set(denorm.values()))
        elif symbols_section.get("normalize"):
            supported_pairs = sorted(symbols_section["normalize"].keys())

        # Regional restrictions
        regional_restrictions: list[str] = data.get(
            "regional_restrictions", []
        )

        config = ExchangeConfig(
            exchange_id=exchange_id,
            display_name=display_name,
            status=status,
            has_testnet=has_testnet,
            pair_format=pair_format,
            default_quote=default_quote,
            min_order_usd=min_order_usd,
            maker_fee_bps=maker_fee_bps,
            taker_fee_bps=taker_fee_bps,
            supported_pairs=supported_pairs,
            regional_restrictions=regional_restrictions,
            raw=data,
        )
        self._configs[exchange_id] = config
        logger.debug("Loaded exchange config: %s (%s)", exchange_id, status)
