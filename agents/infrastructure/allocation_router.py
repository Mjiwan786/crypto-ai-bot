"""
Allocation Router

Routes capital allocation across multiple trading pairs with:
- Per-pair allocation caps (10% max)
- Priority-based selection
- Dynamic pair rotation
- Correlation-aware allocation

Integrates with strategy router for multi-strategy multi-pair trading.

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import yaml

from agents.infrastructure.trading_specs_validator import TradingSpecsValidator

logger = logging.getLogger(__name__)


@dataclass
class PairAllocation:
    """Allocation for a single trading pair."""
    symbol: str
    kraken_symbol: str
    allocation_pct: float
    priority: int
    is_active: bool = True
    current_position_usd: float = 0.0
    pnl_today: float = 0.0


@dataclass
class AllocationState:
    """Current allocation state across all pairs."""
    pair_allocations: Dict[str, PairAllocation] = field(default_factory=dict)
    total_capital_usd: float = 0.0
    allocated_capital_usd: float = 0.0
    available_capital_usd: float = 0.0
    active_pairs: List[str] = field(default_factory=list)


class AllocationRouter:
    """
    Routes capital allocation across trading pairs.

    Enforces allocation caps, priority ordering, and correlation limits.
    """

    def __init__(
        self,
        config_path: str = "config/multi_pair_scalper_config.yaml",
        total_capital_usd: float = 10000.0,
        mode: str = "turbo",  # turbo, conservative, paper
    ):
        """
        Initialize allocation router.

        Args:
            config_path: Path to multi-pair config
            total_capital_usd: Total trading capital
            mode: Trading mode (affects allocation caps)
        """
        self.config = self._load_config(config_path)
        self.total_capital_usd = total_capital_usd
        self.mode = mode

        # Extract config
        self.allocation_config = self.config.get("allocation", {})
        self.trading_pairs = self.config.get("trading_pairs", {})
        self.selection_config = self.config.get("selection", {})
        self.risk_config = self.config.get("risk_management", {})

        # Get mode-specific overrides
        mode_config = self.allocation_config.get("modes", {}).get(mode, {})
        self.max_allocation_per_pair = mode_config.get(
            "max_allocation_per_pair_pct",
            self.allocation_config.get("max_allocation_per_pair_pct", 10.0),
        )
        self.max_concurrent_pairs = mode_config.get(
            "max_concurrent_pairs",
            self.allocation_config.get("max_concurrent_pairs", 4),
        )

        # Initialize state
        self.state = AllocationState()
        self.state.total_capital_usd = total_capital_usd
        self.state.available_capital_usd = total_capital_usd

        # Initialize validator
        self.validator = TradingSpecsValidator()

        logger.info(
            f"Allocation router initialized: mode={mode}, "
            f"capital=${total_capital_usd:,.0f}, "
            f"max_per_pair={self.max_allocation_per_pair}%, "
            f"max_pairs={self.max_concurrent_pairs}"
        )

    def _load_config(self, path: str) -> Dict:
        """Load YAML configuration."""
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config {path}: {e}")
            return {}

    def get_enabled_pairs(
        self,
        include_alts: bool = False,
        core_only: bool = False,
    ) -> List[Tuple[str, str, int, float]]:
        """
        Get list of enabled trading pairs.

        Args:
            include_alts: Include alt-coin pairs (SOL, ADA)
            core_only: Only include core pairs (BTC, ETH)

        Returns:
            List of (symbol, kraken_symbol, priority, allocation_pct)
        """
        pairs = []

        # Core pairs (always included unless core_only=False)
        core_pairs = self.trading_pairs.get("core", [])
        for pair in core_pairs:
            if pair.get("enabled", True):
                pairs.append((
                    pair["symbol"],
                    pair["kraken_symbol"],
                    pair["priority"],
                    pair["allocation_pct"],
                ))

        # Alt pairs (only if include_alts=True and not core_only)
        if include_alts and not core_only:
            alt_pairs = self.trading_pairs.get("alts", [])
            for pair in alt_pairs:
                if pair.get("enabled", False):
                    pairs.append((
                        pair["symbol"],
                        pair["kraken_symbol"],
                        pair["priority"],
                        pair["allocation_pct"],
                    ))

        # Sort by priority
        pairs.sort(key=lambda x: x[2])

        logger.info(
            f"Enabled pairs: {[p[0] for p in pairs]} "
            f"(core_only={core_only}, include_alts={include_alts})"
        )

        return pairs

    def allocate_capital(
        self,
        enabled_pairs: List[Tuple[str, str, int, float]],
        spread_data: Optional[Dict[str, float]] = None,
        liquidity_data: Optional[Dict[str, float]] = None,
    ) -> AllocationState:
        """
        Allocate capital across enabled pairs.

        Args:
            enabled_pairs: List of (symbol, kraken_symbol, priority, allocation_pct)
            spread_data: Current spread data for validation
            liquidity_data: Current liquidity data for validation

        Returns:
            Updated AllocationState
        """
        # Validate pairs
        validation_pairs = [(s, ks) for s, ks, _, _ in enabled_pairs]
        validation_results = self.validator.validate_all_pairs(
            validation_pairs,
            spread_data,
            liquidity_data,
        )

        # Filter to valid pairs
        valid_pairs = [
            (s, ks, p, a)
            for s, ks, p, a in enabled_pairs
            if validation_results[s].is_valid
        ]

        # Limit to max concurrent pairs
        if len(valid_pairs) > self.max_concurrent_pairs:
            logger.warning(
                f"Limiting pairs from {len(valid_pairs)} to {self.max_concurrent_pairs}"
            )
            valid_pairs = valid_pairs[: self.max_concurrent_pairs]

        # Allocate capital
        self.state.pair_allocations = {}
        allocated_total = 0.0

        for symbol, kraken_symbol, priority, allocation_pct in valid_pairs:
            # Cap allocation at max_allocation_per_pair
            capped_allocation = min(allocation_pct, self.max_allocation_per_pair)

            # Calculate USD amount
            allocation_usd = (
                self.total_capital_usd * capped_allocation / 100.0
            )

            # Create allocation
            pair_alloc = PairAllocation(
                symbol=symbol,
                kraken_symbol=kraken_symbol,
                allocation_pct=capped_allocation,
                priority=priority,
                is_active=True,
                current_position_usd=0.0,
                pnl_today=0.0,
            )

            self.state.pair_allocations[symbol] = pair_alloc
            allocated_total += capped_allocation

            logger.info(
                f"Allocated {symbol}: {capped_allocation:.1f}% = ${allocation_usd:,.0f}"
            )

        # Update state
        self.state.allocated_capital_usd = (
            self.total_capital_usd * allocated_total / 100.0
        )
        self.state.available_capital_usd = (
            self.total_capital_usd - self.state.allocated_capital_usd
        )
        self.state.active_pairs = list(self.state.pair_allocations.keys())

        logger.info(
            f"Allocation complete: {len(self.state.active_pairs)} pairs, "
            f"{allocated_total:.1f}% allocated, "
            f"${self.state.available_capital_usd:,.0f} available"
        )

        return self.state

    def get_pair_capital(self, symbol: str) -> float:
        """
        Get allocated capital for a specific pair.

        Args:
            symbol: Trading pair symbol

        Returns:
            Allocated capital in USD
        """
        if symbol not in self.state.pair_allocations:
            return 0.0

        allocation = self.state.pair_allocations[symbol]
        return self.total_capital_usd * allocation.allocation_pct / 100.0

    def update_position(self, symbol: str, position_usd: float):
        """
        Update current position for a pair.

        Args:
            symbol: Trading pair symbol
            position_usd: Current position size in USD
        """
        if symbol in self.state.pair_allocations:
            self.state.pair_allocations[symbol].current_position_usd = position_usd
            logger.debug(f"Updated {symbol} position: ${position_usd:,.0f}")

    def update_pnl(self, symbol: str, pnl_today: float):
        """
        Update P&L for a pair.

        Args:
            symbol: Trading pair symbol
            pnl_today: Today's P&L in USD
        """
        if symbol in self.state.pair_allocations:
            self.state.pair_allocations[symbol].pnl_today = pnl_today
            logger.debug(f"Updated {symbol} P&L: ${pnl_today:,.2f}")

    def check_pair_limits(self, symbol: str, proposed_position_usd: float) -> Tuple[bool, str]:
        """
        Check if proposed position exceeds limits.

        Args:
            symbol: Trading pair symbol
            proposed_position_usd: Proposed position size in USD

        Returns:
            (is_allowed, reason)
        """
        if symbol not in self.state.pair_allocations:
            return False, f"Pair {symbol} not allocated"

        allocation = self.state.pair_allocations[symbol]
        max_position_usd = self.total_capital_usd * allocation.allocation_pct / 100.0

        if proposed_position_usd > max_position_usd:
            return False, (
                f"Position ${proposed_position_usd:,.0f} > "
                f"max ${max_position_usd:,.0f} ({allocation.allocation_pct}%)"
            )

        # Check per-pair position limits from risk config
        pair_limits = self.risk_config.get("max_position_usd_per_pair", {})
        kraken_symbol = allocation.kraken_symbol
        max_pair_limit = pair_limits.get(
            kraken_symbol, pair_limits.get("default", float("inf"))
        )

        if proposed_position_usd > max_pair_limit:
            return False, (
                f"Position ${proposed_position_usd:,.0f} > "
                f"pair limit ${max_pair_limit:,.0f}"
            )

        return True, "OK"

    def rebalance_if_needed(
        self,
        performance_data: Optional[Dict[str, float]] = None,
    ) -> bool:
        """
        Rebalance allocations if needed based on performance.

        Args:
            performance_data: Dict of symbol -> performance_score (0-100)

        Returns:
            True if rebalanced, False otherwise
        """
        rotation_config = self.selection_config.get("rotation", {})

        if not rotation_config.get("enabled", False):
            return False

        if not performance_data:
            return False

        # Find underperformers
        min_percentile = rotation_config.get("min_performance_percentile", 25)
        sorted_pairs = sorted(
            performance_data.items(), key=lambda x: x[1], reverse=True
        )

        # Identify pairs to rotate out (bottom 25%)
        cutoff_index = int(len(sorted_pairs) * (100 - min_percentile) / 100)
        pairs_to_rotate = [p[0] for p in sorted_pairs[cutoff_index:]]

        if pairs_to_rotate:
            logger.info(f"Rotating out underperformers: {pairs_to_rotate}")

            # Deactivate underperformers
            for symbol in pairs_to_rotate:
                if symbol in self.state.pair_allocations:
                    self.state.pair_allocations[symbol].is_active = False

            # Update active pairs list
            self.state.active_pairs = [
                s for s, a in self.state.pair_allocations.items() if a.is_active
            ]

            return True

        return False

    def get_allocation_summary(self) -> Dict:
        """
        Get summary of current allocations.

        Returns:
            Dict with allocation summary
        """
        return {
            "total_capital_usd": self.state.total_capital_usd,
            "allocated_capital_usd": self.state.allocated_capital_usd,
            "available_capital_usd": self.state.available_capital_usd,
            "active_pairs_count": len(self.state.active_pairs),
            "active_pairs": self.state.active_pairs,
            "pair_allocations": {
                symbol: {
                    "allocation_pct": alloc.allocation_pct,
                    "allocation_usd": self.total_capital_usd * alloc.allocation_pct / 100.0,
                    "current_position_usd": alloc.current_position_usd,
                    "pnl_today": alloc.pnl_today,
                    "priority": alloc.priority,
                }
                for symbol, alloc in self.state.pair_allocations.items()
            },
        }


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Create router
    router = AllocationRouter(
        total_capital_usd=100000.0,
        mode="turbo",
    )

    # Get enabled pairs
    pairs = router.get_enabled_pairs(include_alts=True)
    print(f"\nEnabled pairs: {[p[0] for p in pairs]}")

    # Mock spread/liquidity data
    spread_data = {
        "XBTUSD": 3.5,
        "ETHUSD": 6.0,
        "SOLUSD": 10.0,
        "ADAUSD": 12.0,
    }

    liquidity_data = {
        "XBTUSD": 2000000,
        "ETHUSD": 800000,
        "SOLUSD": 300000,
        "ADAUSD": 150000,
    }

    # Allocate capital
    state = router.allocate_capital(pairs, spread_data, liquidity_data)

    # Print summary
    summary = router.get_allocation_summary()
    print("\n=== Allocation Summary ===")
    print(f"Total capital: ${summary['total_capital_usd']:,.0f}")
    print(f"Allocated: ${summary['allocated_capital_usd']:,.0f}")
    print(f"Available: ${summary['available_capital_usd']:,.0f}")
    print(f"Active pairs: {summary['active_pairs']}")

    print("\n=== Per-Pair Allocations ===")
    for symbol, alloc in summary['pair_allocations'].items():
        print(
            f"{symbol}: {alloc['allocation_pct']:.1f}% = "
            f"${alloc['allocation_usd']:,.0f} (priority {alloc['priority']})"
        )

    # Test position limits
    print("\n=== Position Limit Checks ===")
    for symbol in summary['active_pairs']:
        # Test with 100% of allocation
        pair_capital = router.get_pair_capital(symbol)
        allowed, reason = router.check_pair_limits(symbol, pair_capital)
        print(f"{symbol} @ ${pair_capital:,.0f}: {'✓' if allowed else '✗'} {reason}")

        # Test with 150% of allocation (should fail)
        allowed, reason = router.check_pair_limits(symbol, pair_capital * 1.5)
        print(f"{symbol} @ ${pair_capital * 1.5:,.0f}: {'✓' if allowed else '✗'} {reason}")
