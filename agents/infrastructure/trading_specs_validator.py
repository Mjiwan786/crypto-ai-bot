"""
Trading Specs Validator

Validates trading pairs against Kraken specs before allowing scalping:
- Spread within configured limits (bps)
- Precision/tick sizes available
- Sufficient liquidity
- Pair is tradable today

Fail-fast approach: reject pairs that don't meet requirements.

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


@dataclass
class TradingSpec:
    """Trading specification for a pair."""
    symbol: str
    kraken_symbol: str
    price_decimals: int
    size_decimals: int
    tick_size: float
    lot_size: float
    min_notional: float
    max_spread_bps: float
    min_liquidity_usd: float
    is_tradable: bool = True


@dataclass
class ValidationResult:
    """Result of trading spec validation."""
    is_valid: bool
    symbol: str
    failures: List[str]
    warnings: List[str]
    spec: Optional[TradingSpec] = None


class TradingSpecsValidator:
    """
    Validates trading pairs against Kraken specs.

    Ensures pairs meet minimum requirements for spread, precision,
    and liquidity before allowing trading.
    """

    def __init__(
        self,
        kraken_config_path: str = "config/exchange_configs/kraken.yaml",
        multi_pair_config_path: str = "config/multi_pair_scalper_config.yaml",
    ):
        """
        Initialize validator.

        Args:
            kraken_config_path: Path to Kraken exchange config
            multi_pair_config_path: Path to multi-pair scalper config
        """
        self.kraken_config = self._load_yaml(kraken_config_path)
        self.multi_pair_config = self._load_yaml(multi_pair_config_path)

        # Extract configs
        self.trading_specs = self.kraken_config.get("trading_specs", {})
        self.risk_guards = self.kraken_config.get("risk_guards", {})
        self.validation_config = self.multi_pair_config.get("validation", {})

        logger.info("Trading specs validator initialized")

    def _load_yaml(self, path: str) -> Dict:
        """Load YAML configuration file."""
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config {path}: {e}")
            return {}

    def validate_pair(
        self,
        symbol: str,
        kraken_symbol: str,
        current_spread_bps: Optional[float] = None,
        current_liquidity_usd: Optional[float] = None,
    ) -> ValidationResult:
        """
        Validate a trading pair against specs.

        Args:
            symbol: Internal symbol (e.g., "BTC/USD")
            kraken_symbol: Kraken symbol (e.g., "XBTUSD")
            current_spread_bps: Current spread in basis points
            current_liquidity_usd: Current liquidity in USD

        Returns:
            ValidationResult with pass/fail and details
        """
        failures = []
        warnings = []

        # Get precision specs
        precision = self.trading_specs.get("precision", {}).get(kraken_symbol)
        if not precision:
            failures.append(f"No precision data for {kraken_symbol}")
            return ValidationResult(
                is_valid=False,
                symbol=symbol,
                failures=failures,
                warnings=warnings,
            )

        # Get spread limits
        max_spread_config = self.validation_config.get("max_spread_bps", {})
        max_spread_bps = max_spread_config.get(
            kraken_symbol, max_spread_config.get("default", 20)
        )

        # Get liquidity limits
        min_liquidity_config = self.validation_config.get("min_liquidity_usd", {})
        min_liquidity_usd = min_liquidity_config.get(
            kraken_symbol, min_liquidity_config.get("default", 50000)
        )

        # Create spec object
        spec = TradingSpec(
            symbol=symbol,
            kraken_symbol=kraken_symbol,
            price_decimals=precision.get("price_dp", 2),
            size_decimals=precision.get("size_dp", 6),
            tick_size=precision.get("tick_size", 0.01),
            lot_size=precision.get("lot_size", 0.000001),
            min_notional=precision.get("min_notional", 5.0),
            max_spread_bps=max_spread_bps,
            min_liquidity_usd=min_liquidity_usd,
        )

        # Validation 1: Spread check
        if current_spread_bps is not None:
            if current_spread_bps > max_spread_bps:
                failures.append(
                    f"Spread {current_spread_bps:.1f} bps > max {max_spread_bps:.1f} bps"
                )
            elif current_spread_bps > max_spread_bps * 0.8:
                warnings.append(
                    f"Spread {current_spread_bps:.1f} bps near limit {max_spread_bps:.1f} bps"
                )

        # Validation 2: Liquidity check
        if current_liquidity_usd is not None:
            if current_liquidity_usd < min_liquidity_usd:
                failures.append(
                    f"Liquidity ${current_liquidity_usd:,.0f} < min ${min_liquidity_usd:,.0f}"
                )
            elif current_liquidity_usd < min_liquidity_usd * 1.5:
                warnings.append(
                    f"Liquidity ${current_liquidity_usd:,.0f} near min ${min_liquidity_usd:,.0f}"
                )

        # Validation 3: Precision data complete
        required_fields = ["price_dp", "size_dp", "tick_size", "lot_size", "min_notional"]
        missing_fields = [f for f in required_fields if f not in precision]
        if missing_fields:
            failures.append(f"Missing precision fields: {', '.join(missing_fields)}")

        # Validation 4: Reasonable tick/lot sizes
        if spec.tick_size <= 0:
            failures.append(f"Invalid tick_size: {spec.tick_size}")
        if spec.lot_size <= 0:
            failures.append(f"Invalid lot_size: {spec.lot_size}")

        is_valid = len(failures) == 0

        logger.info(
            f"Validation {symbol} ({'PASS' if is_valid else 'FAIL'}): "
            f"{len(failures)} failures, {len(warnings)} warnings"
        )

        return ValidationResult(
            is_valid=is_valid,
            symbol=symbol,
            failures=failures,
            warnings=warnings,
            spec=spec if is_valid else None,
        )

    def validate_all_pairs(
        self,
        pairs: List[Tuple[str, str]],  # List of (symbol, kraken_symbol)
        spread_data: Optional[Dict[str, float]] = None,
        liquidity_data: Optional[Dict[str, float]] = None,
    ) -> Dict[str, ValidationResult]:
        """
        Validate multiple pairs.

        Args:
            pairs: List of (symbol, kraken_symbol) tuples
            spread_data: Dict of kraken_symbol -> current_spread_bps
            liquidity_data: Dict of kraken_symbol -> current_liquidity_usd

        Returns:
            Dict mapping symbol -> ValidationResult
        """
        results = {}

        for symbol, kraken_symbol in pairs:
            current_spread = (
                spread_data.get(kraken_symbol) if spread_data else None
            )
            current_liquidity = (
                liquidity_data.get(kraken_symbol) if liquidity_data else None
            )

            result = self.validate_pair(
                symbol,
                kraken_symbol,
                current_spread,
                current_liquidity,
            )

            results[symbol] = result

        # Summary
        valid_count = sum(1 for r in results.values() if r.is_valid)
        logger.info(
            f"Validated {len(pairs)} pairs: {valid_count} valid, "
            f"{len(pairs) - valid_count} invalid"
        )

        return results

    def get_tradable_pairs(
        self,
        pairs: List[Tuple[str, str]],
        spread_data: Optional[Dict[str, float]] = None,
        liquidity_data: Optional[Dict[str, float]] = None,
        fail_fast: bool = True,
    ) -> List[str]:
        """
        Get list of tradable pairs after validation.

        Args:
            pairs: List of (symbol, kraken_symbol) tuples
            spread_data: Current spread data
            liquidity_data: Current liquidity data
            fail_fast: If True, skip invalid pairs; if False, halt on first failure

        Returns:
            List of valid symbols
        """
        results = self.validate_all_pairs(pairs, spread_data, liquidity_data)

        tradable = []
        for symbol, result in results.items():
            if result.is_valid:
                tradable.append(symbol)
            else:
                if fail_fast:
                    logger.warning(
                        f"Skipping {symbol}: {', '.join(result.failures)}"
                    )
                else:
                    raise ValueError(
                        f"Validation failed for {symbol}: {', '.join(result.failures)}"
                    )

        logger.info(f"Tradable pairs: {tradable}")
        return tradable

    def check_allocation_sum(
        self,
        pair_allocations: Dict[str, float],
        max_total: float = 100.0,
    ) -> Tuple[bool, float, List[str]]:
        """
        Check that sum of allocations doesn't exceed max.

        Args:
            pair_allocations: Dict of symbol -> allocation_pct
            max_total: Maximum total allocation %

        Returns:
            (is_valid, actual_sum, violations)
        """
        total = sum(pair_allocations.values())
        violations = []

        if total > max_total:
            violations.append(
                f"Total allocation {total:.1f}% > max {max_total:.1f}%"
            )

        # Check per-pair caps
        max_per_pair = self.multi_pair_config.get("allocation", {}).get(
            "max_allocation_per_pair_pct", 10.0
        )

        for symbol, allocation in pair_allocations.items():
            if allocation > max_per_pair:
                violations.append(
                    f"{symbol}: {allocation:.1f}% > max {max_per_pair:.1f}%"
                )

        is_valid = len(violations) == 0

        if not is_valid:
            logger.error(f"Allocation validation failed: {violations}")
        else:
            logger.info(f"Allocation validation passed: {total:.1f}% total")

        return is_valid, total, violations


def validate_spread_from_orderbook(orderbook_data: Dict) -> float:
    """
    Calculate spread in basis points from orderbook data.

    Args:
        orderbook_data: Orderbook with 'bids' and 'asks'

    Returns:
        Spread in basis points
    """
    try:
        best_bid = float(orderbook_data["bids"][0][0])
        best_ask = float(orderbook_data["asks"][0][0])

        mid_price = (best_bid + best_ask) / 2
        spread_bps = ((best_ask - best_bid) / mid_price) * 10000

        return spread_bps

    except (KeyError, IndexError, ValueError) as e:
        logger.error(f"Error calculating spread: {e}")
        return float("inf")  # Return infinite spread on error


def validate_liquidity_from_orderbook(
    orderbook_data: Dict,
    depth_levels: int = 5,
) -> float:
    """
    Calculate liquidity in USD from orderbook depth.

    Args:
        orderbook_data: Orderbook with 'bids' and 'asks'
        depth_levels: Number of levels to sum

    Returns:
        Liquidity in USD (sum of bid/ask volume * price)
    """
    try:
        bids = orderbook_data["bids"][:depth_levels]
        asks = orderbook_data["asks"][:depth_levels]

        bid_liquidity = sum(float(price) * float(volume) for price, volume in bids)
        ask_liquidity = sum(float(price) * float(volume) for price, volume in asks)

        total_liquidity = bid_liquidity + ask_liquidity

        return total_liquidity

    except (KeyError, IndexError, ValueError) as e:
        logger.error(f"Error calculating liquidity: {e}")
        return 0.0


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    validator = TradingSpecsValidator()

    # Test pairs
    pairs = [
        ("BTC/USD", "XBTUSD"),
        ("ETH/USD", "ETHUSD"),
        ("SOL/USD", "SOLUSD"),
        ("ADA/USD", "ADAUSD"),
    ]

    # Mock spread data (would come from live orderbook)
    spread_data = {
        "XBTUSD": 3.5,  # 3.5 bps - good
        "ETHUSD": 6.0,  # 6 bps - acceptable
        "SOLUSD": 10.0,  # 10 bps - borderline
        "ADAUSD": 12.0,  # 12 bps - acceptable for ADA
    }

    # Mock liquidity data
    liquidity_data = {
        "XBTUSD": 2000000,  # $2M - excellent
        "ETHUSD": 800000,  # $800K - good
        "SOLUSD": 300000,  # $300K - acceptable
        "ADAUSD": 150000,  # $150K - acceptable
    }

    # Validate all pairs
    results = validator.validate_all_pairs(pairs, spread_data, liquidity_data)

    # Print results
    for symbol, result in results.items():
        print(f"\n{symbol}: {'✓ VALID' if result.is_valid else '✗ INVALID'}")
        if result.failures:
            print(f"  Failures: {result.failures}")
        if result.warnings:
            print(f"  Warnings: {result.warnings}")
        if result.spec:
            print(f"  Spec: {result.spec}")

    # Get tradable pairs
    tradable = validator.get_tradable_pairs(pairs, spread_data, liquidity_data)
    print(f"\nTradable pairs: {tradable}")

    # Check allocation sum
    allocations = {
        "BTC/USD": 10.0,
        "ETH/USD": 10.0,
        "SOL/USD": 10.0,
        "ADA/USD": 10.0,
    }
    is_valid, total, violations = validator.check_allocation_sum(allocations)
    print(f"\nAllocation check: {'✓ VALID' if is_valid else '✗ INVALID'} (total: {total}%)")
    if violations:
        print(f"  Violations: {violations}")
