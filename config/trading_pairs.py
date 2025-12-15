"""
Canonical Trading Pairs Configuration

This module is the SINGLE SOURCE OF TRUTH for all supported trading pairs
across the entire crypto-ai-bot ecosystem (engine, signals-api, signals-site).

PRD-001 Compliance:
- Pair format: BASE/QUOTE (e.g., BTC/USD)
- Kraken normalization maps: BTC/USD -> XBTUSD, etc.
- Stream format: BTC/USD -> BTC-USD for Redis streams

IMPORTANT: When modifying this file, ensure downstream components are updated:
- signals-api: Uses TRADING_PAIRS env var (should match this list)
- signals-site: web/lib/trading-pairs.ts (should match this list)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class LiquidityTier(str, Enum):
    """Liquidity tier classification for trading pairs."""
    HIGH = "high"      # Tier 1: BTC, ETH
    MEDIUM = "medium"  # Tier 2: SOL
    LOW = "low"        # Tier 3: LINK, etc.


@dataclass(frozen=True)
class TradingPair:
    """
    Canonical trading pair definition.

    Attributes:
        symbol: Standard format (e.g., "BTC/USD")
        kraken_symbol: Kraken API format (e.g., "XBTUSD")
        base: Base currency (e.g., "BTC")
        quote: Quote currency (e.g., "USD")
        name: Human-readable name (e.g., "Bitcoin")
        description: Brief description
        tier: Liquidity tier (1=high, 2=medium, 3=low)
        liquidity_tier: LiquidityTier enum value
        enabled: Whether this pair is currently active
        min_volume: Minimum order volume
        tick_size: Price tick size
        min_notional: Minimum order notional (USD)
        spread_tolerance_bps: Max spread in basis points
        ml_priority: ML model priority (lower = higher priority)
        note: Optional note (e.g., exchange limitations)
    """
    symbol: str
    kraken_symbol: str
    base: str
    quote: str
    name: str
    description: str
    tier: int
    liquidity_tier: LiquidityTier
    enabled: bool = True
    min_volume: float = 0.0001
    tick_size: float = 0.01
    min_notional: float = 5.0
    spread_tolerance_bps: float = 10.0
    ml_priority: int = 5
    note: Optional[str] = None

    @property
    def stream_symbol(self) -> str:
        """Get Redis stream format (e.g., BTC-USD)."""
        return self.symbol.replace("/", "-")

    @property
    def display(self) -> str:
        """Get display format (same as symbol for consistency)."""
        return self.symbol


# =============================================================================
# CANONICAL TRADING PAIRS LIST
# =============================================================================
# This is the authoritative list of all supported trading pairs.
# PRD-001 specifies: BTC/USD, ETH/USD, SOL/USD, MATIC/USD, LINK/USD
# Note: MATIC/USD is listed per PRD-001 but disabled - Kraken WS doesn't support it
# =============================================================================

TRADING_PAIRS_CONFIG: List[TradingPair] = [
    # Tier 1: High Liquidity (Core pairs)
    TradingPair(
        symbol="BTC/USD",
        kraken_symbol="XBTUSD",
        base="BTC",
        quote="USD",
        name="Bitcoin",
        description="The original cryptocurrency, highest market cap and liquidity",
        tier=1,
        liquidity_tier=LiquidityTier.HIGH,
        enabled=True,
        min_volume=0.0001,
        tick_size=0.1,
        min_notional=5.0,
        spread_tolerance_bps=5,
        ml_priority=1,
    ),
    TradingPair(
        symbol="ETH/USD",
        kraken_symbol="ETHUSD",
        base="ETH",
        quote="USD",
        name="Ethereum",
        description="Leading smart contract platform, second largest crypto by market cap",
        tier=1,
        liquidity_tier=LiquidityTier.HIGH,
        enabled=True,
        min_volume=0.001,
        tick_size=0.01,
        min_notional=5.0,
        spread_tolerance_bps=5,
        ml_priority=1,
    ),

    # Tier 2: Medium Liquidity
    TradingPair(
        symbol="SOL/USD",
        kraken_symbol="SOLUSD",
        base="SOL",
        quote="USD",
        name="Solana",
        description="High-performance blockchain for decentralized apps",
        tier=2,
        liquidity_tier=LiquidityTier.MEDIUM,
        enabled=True,
        min_volume=0.01,
        tick_size=0.001,
        min_notional=5.0,
        spread_tolerance_bps=8,
        ml_priority=3,
    ),

    # Tier 3: Lower Liquidity
    TradingPair(
        symbol="LINK/USD",
        kraken_symbol="LINKUSD",
        base="LINK",
        quote="USD",
        name="Chainlink",
        description="Decentralized oracle network connecting smart contracts to real-world data",
        tier=3,
        liquidity_tier=LiquidityTier.LOW,
        enabled=True,
        min_volume=0.1,
        tick_size=0.001,
        min_notional=5.0,
        spread_tolerance_bps=15,
        ml_priority=5,
    ),

    # MATIC/USD: Listed per PRD-001 but NOT supported by Kraken WebSocket
    # Kraken returns "Currency pair not supported MATIC/USD" error
    # Kept in config for completeness but disabled until alternative exchange integration
    TradingPair(
        symbol="MATIC/USD",
        kraken_symbol="MATICUSD",
        base="MATIC",
        quote="USD",
        name="Polygon",
        description="Ethereum scaling solution with fast, low-cost transactions",
        tier=3,
        liquidity_tier=LiquidityTier.LOW,
        enabled=False,  # DISABLED: Not available on Kraken WS
        min_volume=1.0,
        tick_size=0.0001,
        min_notional=5.0,
        spread_tolerance_bps=15,
        ml_priority=6,
        note="Requires ccxt/Binance integration - not available on Kraken WS",
    ),
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_all_pairs() -> List[TradingPair]:
    """Get all configured trading pairs (including disabled)."""
    return TRADING_PAIRS_CONFIG.copy()


def get_enabled_pairs() -> List[TradingPair]:
    """Get only enabled trading pairs (for active trading)."""
    return [p for p in TRADING_PAIRS_CONFIG if p.enabled]


def get_pair_symbols(enabled_only: bool = True) -> List[str]:
    """
    Get list of trading pair symbols.

    Args:
        enabled_only: If True, only return enabled pairs

    Returns:
        List of symbols in BASE/QUOTE format (e.g., ["BTC/USD", "ETH/USD"])
    """
    pairs = get_enabled_pairs() if enabled_only else get_all_pairs()
    return [p.symbol for p in pairs]


def get_kraken_symbols(enabled_only: bool = True) -> List[str]:
    """
    Get list of Kraken-formatted symbols for WebSocket subscription.

    Args:
        enabled_only: If True, only return enabled pairs

    Returns:
        List of Kraken symbols (e.g., ["XBTUSD", "ETHUSD"])
    """
    pairs = get_enabled_pairs() if enabled_only else get_all_pairs()
    return [p.kraken_symbol for p in pairs]


def get_stream_symbols(enabled_only: bool = True) -> List[str]:
    """
    Get list of Redis stream-formatted symbols.

    Args:
        enabled_only: If True, only return enabled pairs

    Returns:
        List of stream symbols (e.g., ["BTC-USD", "ETH-USD"])
    """
    pairs = get_enabled_pairs() if enabled_only else get_all_pairs()
    return [p.stream_symbol for p in pairs]


def get_pair_by_symbol(symbol: str) -> Optional[TradingPair]:
    """
    Get a trading pair by its symbol.

    Args:
        symbol: Symbol in any format (BTC/USD, BTC-USD, XBTUSD)

    Returns:
        TradingPair if found, None otherwise
    """
    # Normalize symbol
    normalized = symbol.upper().replace("-", "/")

    for pair in TRADING_PAIRS_CONFIG:
        if (pair.symbol == normalized or
            pair.kraken_symbol == symbol.upper() or
            pair.stream_symbol == symbol.upper()):
            return pair
    return None


def symbol_to_kraken(symbol: str) -> Optional[str]:
    """
    Convert standard symbol to Kraken format.

    Args:
        symbol: Standard format (e.g., "BTC/USD" or "BTC-USD")

    Returns:
        Kraken format (e.g., "XBTUSD") or None if not found
    """
    pair = get_pair_by_symbol(symbol)
    return pair.kraken_symbol if pair else None


def kraken_to_symbol(kraken_symbol: str) -> Optional[str]:
    """
    Convert Kraken symbol to standard format.

    Args:
        kraken_symbol: Kraken format (e.g., "XBTUSD")

    Returns:
        Standard format (e.g., "BTC/USD") or None if not found
    """
    for pair in TRADING_PAIRS_CONFIG:
        if pair.kraken_symbol == kraken_symbol.upper():
            return pair.symbol
    return None


def symbol_to_stream(symbol: str) -> str:
    """
    Convert standard symbol to Redis stream format.

    Args:
        symbol: Standard format (e.g., "BTC/USD")

    Returns:
        Stream format (e.g., "BTC-USD")
    """
    return symbol.replace("/", "-")


def stream_to_symbol(stream_symbol: str) -> str:
    """
    Convert Redis stream format to standard symbol.

    Args:
        stream_symbol: Stream format (e.g., "BTC-USD")

    Returns:
        Standard format (e.g., "BTC/USD")
    """
    return stream_symbol.replace("-", "/")


def get_pairs_by_tier(tier: int, enabled_only: bool = True) -> List[TradingPair]:
    """
    Get trading pairs by liquidity tier.

    Args:
        tier: Tier number (1=high, 2=medium, 3=low)
        enabled_only: If True, only return enabled pairs

    Returns:
        List of trading pairs in that tier
    """
    pairs = get_enabled_pairs() if enabled_only else get_all_pairs()
    return [p for p in pairs if p.tier == tier]


def get_pairs_csv(enabled_only: bool = True) -> str:
    """
    Get comma-separated list of pair symbols.
    Useful for environment variable configuration.

    Args:
        enabled_only: If True, only return enabled pairs

    Returns:
        CSV string (e.g., "BTC/USD,ETH/USD,SOL/USD,LINK/USD")
    """
    return ",".join(get_pair_symbols(enabled_only))


# =============================================================================
# KRAKEN NORMALIZATION MAPS
# =============================================================================
# These maps ensure consistent symbol handling across the system

def get_normalize_map() -> Dict[str, str]:
    """
    Get mapping from standard symbols to Kraken symbols.

    Returns:
        Dict mapping (e.g., {"BTC/USD": "XBTUSD"})
    """
    return {p.symbol: p.kraken_symbol for p in TRADING_PAIRS_CONFIG}


def get_denormalize_map() -> Dict[str, str]:
    """
    Get mapping from Kraken symbols to standard symbols.

    Returns:
        Dict mapping (e.g., {"XBTUSD": "BTC/USD"})
    """
    return {p.kraken_symbol: p.symbol for p in TRADING_PAIRS_CONFIG}


# =============================================================================
# VALIDATION
# =============================================================================

def is_valid_pair(symbol: str) -> bool:
    """
    Check if a symbol is a valid (configured) trading pair.

    Args:
        symbol: Symbol in any format

    Returns:
        True if valid, False otherwise
    """
    return get_pair_by_symbol(symbol) is not None


def is_enabled_pair(symbol: str) -> bool:
    """
    Check if a symbol is an enabled trading pair.

    Args:
        symbol: Symbol in any format

    Returns:
        True if enabled, False otherwise
    """
    pair = get_pair_by_symbol(symbol)
    return pair is not None and pair.enabled


def validate_pairs_list(symbols: List[str]) -> List[str]:
    """
    Validate a list of symbols and return only valid enabled ones.

    Performs deduplication while preserving order. Invalid and disabled
    pairs are filtered out.

    Args:
        symbols: List of symbols to validate

    Returns:
        List of unique valid enabled symbols in standard format (order preserved)
    """
    valid = []
    seen = set()
    for symbol in symbols:
        pair = get_pair_by_symbol(symbol)
        if pair and pair.enabled and pair.symbol not in seen:
            valid.append(pair.symbol)
            seen.add(pair.symbol)
    return valid


# =============================================================================
# CONSTANTS FOR EASY IMPORT
# =============================================================================

# Default enabled pairs as CSV (for env var defaults)
DEFAULT_TRADING_PAIRS_CSV = get_pairs_csv(enabled_only=True)

# List of enabled pair symbols
ENABLED_PAIR_SYMBOLS = get_pair_symbols(enabled_only=True)

# List of all pair symbols (including disabled)
ALL_PAIR_SYMBOLS = get_pair_symbols(enabled_only=False)


# =============================================================================
# MODULE INFO
# =============================================================================

__all__ = [
    # Data classes
    "TradingPair",
    "LiquidityTier",

    # Configuration
    "TRADING_PAIRS_CONFIG",

    # Getters
    "get_all_pairs",
    "get_enabled_pairs",
    "get_pair_symbols",
    "get_kraken_symbols",
    "get_stream_symbols",
    "get_pair_by_symbol",
    "get_pairs_by_tier",
    "get_pairs_csv",

    # Converters
    "symbol_to_kraken",
    "kraken_to_symbol",
    "symbol_to_stream",
    "stream_to_symbol",

    # Maps
    "get_normalize_map",
    "get_denormalize_map",

    # Validators
    "is_valid_pair",
    "is_enabled_pair",
    "validate_pairs_list",

    # Constants
    "DEFAULT_TRADING_PAIRS_CSV",
    "ENABLED_PAIR_SYMBOLS",
    "ALL_PAIR_SYMBOLS",
]
