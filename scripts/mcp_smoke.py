#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Schema Smoke Test

⚠️ SAFETY: No live trading unless MODE=live and confirmation set.

This is a HERMETIC test that validates MCP schemas and marshaling
WITHOUT requiring network access or Redis connection. It tests:
- Schema validation (Pydantic models)
- JSON serialization/deserialization
- Schema compatibility
- Type safety

NO network traffic. Exit 0 on success, non-zero on failure.

Usage:
    python scripts/mcp_smoke.py [--verbose]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import MCP schemas
try:
    from ai_engine.schemas import Signal as SignalModel
    from ai_engine.schemas import MarketSnapshot, RegimeLabel
    from mcp.schemas import (
        ContextSnapshot,
        Fill,
        Metric,
        OrderIntent,
        OrderType,
        Side,
        Signal as MCPSignal,
    )
except ImportError as e:
    print(f"ERROR: Failed to import schemas: {e}", file=sys.stderr)
    sys.exit(1)

logger = logging.getLogger(__name__)


def test_signal_model() -> bool:
    """
    Test SignalModel schema validation and serialization.

    Returns:
        True if test passes, False otherwise
    """
    logger.info("Testing SignalModel...")

    try:
        # Create valid signal
        signal = SignalModel(
            strategy="breakout",
            exchange="kraken",
            symbol="BTC/USD",
            side="BUY",
            confidence=0.85,
            size_quote_usd=1000.0,
        )

        # Validate model_dump() works
        signal_dict = signal.model_dump()
        assert isinstance(signal_dict, dict)
        assert signal_dict["strategy"] == "breakout"
        assert signal_dict["side"] == "BUY"

        # Validate JSON serialization
        signal_json = signal.model_dump_json()
        assert isinstance(signal_json, str)

        # Validate deserialization
        parsed = json.loads(signal_json)
        assert parsed["symbol"] == "BTC/USD"

        # Validate from_dict works
        signal_copy = SignalModel(**parsed)
        assert signal_copy.symbol == signal.symbol
        assert signal_copy.confidence == signal.confidence

        logger.info("  ✅ SignalModel validation passed")
        return True

    except Exception as e:
        logger.error(f"  ❌ SignalModel test failed: {e}")
        return False


def test_mcp_signal() -> bool:
    """
    Test MCP Signal schema.

    Returns:
        True if test passes, False otherwise
    """
    logger.info("Testing MCP Signal...")

    try:
        # Create valid MCP signal
        signal = MCPSignal(
            strategy="momentum",
            exchange="binance",
            symbol="ETH/USDT",
            side=Side.SELL,
            confidence=0.75,
            size_quote_usd=500.0,
        )

        # Validate model_dump()
        signal_dict = signal.model_dump()
        assert signal_dict["side"] == "SELL"

        # Validate JSON serialization
        signal_json = signal.model_dump_json()
        assert "ETH/USDT" in signal_json

        logger.info("  ✅ MCP Signal validation passed")
        return True

    except Exception as e:
        logger.error(f"  ❌ MCP Signal test failed: {e}")
        return False


def test_order_intent() -> bool:
    """
    Test OrderIntent schema.

    Returns:
        True if test passes, False otherwise
    """
    logger.info("Testing OrderIntent...")

    try:
        # Create valid order intent
        order = OrderIntent(
            client_id="test-order-001",
            type=OrderType.MARKET,
            price=None,
            qty=0.01,
        )

        # Validate model_dump()
        order_dict = order.model_dump()
        assert order_dict["type"] == "MARKET"
        assert order_dict["qty"] == 0.01

        # Validate JSON serialization
        order_json = order.model_dump_json()
        parsed = json.loads(order_json)
        assert parsed["client_id"] == "test-order-001"

        logger.info("  ✅ OrderIntent validation passed")
        return True

    except Exception as e:
        logger.error(f"  ❌ OrderIntent test failed: {e}")
        return False


def test_fill() -> bool:
    """
    Test Fill schema.

    Returns:
        True if test passes, False otherwise
    """
    logger.info("Testing Fill...")

    try:
        # Create valid fill
        fill = Fill(
            price=50000.0,
            qty=0.01,
            side=Side.BUY,
            fee=0.5,
            trade_id="TRADE-12345",
        )

        # Validate model_dump()
        fill_dict = fill.model_dump()
        assert fill_dict["price"] == 50000.0
        assert fill_dict["trade_id"] == "TRADE-12345"

        # Validate JSON serialization
        fill_json = fill.model_dump_json()
        parsed = json.loads(fill_json)
        assert parsed["qty"] == 0.01

        logger.info("  ✅ Fill validation passed")
        return True

    except Exception as e:
        logger.error(f"  ❌ Fill test failed: {e}")
        return False


def test_context_snapshot() -> bool:
    """
    Test ContextSnapshot schema.

    Returns:
        True if test passes, False otherwise
    """
    logger.info("Testing ContextSnapshot...")

    try:
        # Create valid context snapshot
        snapshot = ContextSnapshot(
            env="paper",
            balances={"USDT": 10000.0, "BTC": 0.5},
            open_positions=[],
            last_prices={"BTC/USDT": 50000.0},
        )

        # Validate model_dump()
        snapshot_dict = snapshot.model_dump()
        assert snapshot_dict["env"] == "paper"
        assert "USDT" in snapshot_dict["balances"]

        # Validate JSON serialization
        snapshot_json = snapshot.model_dump_json()
        parsed = json.loads(snapshot_json)
        assert parsed["balances"]["BTC"] == 0.5

        logger.info("  ✅ ContextSnapshot validation passed")
        return True

    except Exception as e:
        logger.error(f"  ❌ ContextSnapshot test failed: {e}")
        return False


def test_metric() -> bool:
    """
    Test Metric schema.

    Returns:
        True if test passes, False otherwise
    """
    logger.info("Testing Metric...")

    try:
        # Create valid metric
        metric = Metric(
            name="pnl_total",
            value=1500.0,
            labels={"strategy": "breakout", "env": "paper"},
        )

        # Validate model_dump()
        metric_dict = metric.model_dump()
        assert metric_dict["name"] == "pnl_total"
        assert metric_dict["value"] == 1500.0

        # Validate JSON serialization
        metric_json = metric.model_dump_json()
        parsed = json.loads(metric_json)
        assert parsed["labels"]["strategy"] == "breakout"

        logger.info("  ✅ Metric validation passed")
        return True

    except Exception as e:
        logger.error(f"  ❌ Metric test failed: {e}")
        return False


def test_market_snapshot() -> bool:
    """
    Test MarketSnapshot schema.

    Returns:
        True if test passes, False otherwise
    """
    logger.info("Testing MarketSnapshot...")

    try:
        # Create valid market snapshot
        snapshot = MarketSnapshot(
            symbol="BTC/USD",
            timeframe="1h",
            timestamp_ms=1704067200000,
            mid_price=50000.0,
            spread_bps=5.0,
            volume_24h=1000000.0,
        )

        # Validate model_dump()
        snapshot_dict = snapshot.model_dump()
        assert snapshot_dict["symbol"] == "BTC/USD"
        assert snapshot_dict["mid_price"] == 50000.0

        # Validate JSON serialization
        snapshot_json = snapshot.model_dump_json()
        parsed = json.loads(snapshot_json)
        assert parsed["timeframe"] == "1h"

        logger.info("  ✅ MarketSnapshot validation passed")
        return True

    except Exception as e:
        logger.error(f"  ❌ MarketSnapshot test failed: {e}")
        return False


def test_regime_label() -> bool:
    """
    Test RegimeLabel enum.

    Returns:
        True if test passes, False otherwise
    """
    logger.info("Testing RegimeLabel...")

    try:
        # Test all regime labels
        bull = RegimeLabel.BULL
        bear = RegimeLabel.BEAR
        chop = RegimeLabel.CHOP

        assert bull.value == "BULL"
        assert bear.value == "BEAR"
        assert chop.value == "CHOP"

        # Test JSON serialization
        snapshot = MarketSnapshot(
            symbol="BTC/USD",
            timeframe="1h",
            timestamp_ms=1704067200000,
            mid_price=50000.0,
            spread_bps=5.0,
            volume_24h=1000000.0,
        )

        # Ensure regime can be serialized
        data = {"regime": RegimeLabel.BULL.value, "snapshot": snapshot.model_dump()}
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["regime"] == "BULL"

        logger.info("  ✅ RegimeLabel validation passed")
        return True

    except Exception as e:
        logger.error(f"  ❌ RegimeLabel test failed: {e}")
        return False


def run_all_tests(verbose: bool = False) -> int:
    """
    Run all hermetic schema tests.

    Args:
        verbose: Enable verbose logging

    Returns:
        Exit code (0=success, 1=failure)
    """
    logger.info("=" * 60)
    logger.info("MCP SCHEMA SMOKE TEST (HERMETIC)")
    logger.info("=" * 60)
    logger.info("Testing schema validation and JSON marshaling...")
    logger.info("No network traffic.")
    logger.info("")

    tests = [
        ("SignalModel", test_signal_model),
        ("MCP Signal", test_mcp_signal),
        ("OrderIntent", test_order_intent),
        ("Fill", test_fill),
        ("ContextSnapshot", test_context_snapshot),
        ("Metric", test_metric),
        ("MarketSnapshot", test_market_snapshot),
        ("RegimeLabel", test_regime_label),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"❌ {test_name} test crashed: {e}")
            if verbose:
                import traceback
                traceback.print_exc()
            failed += 1

    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST RESULTS")
    logger.info("=" * 60)
    logger.info(f"Passed: {passed}/{len(tests)}")
    logger.info(f"Failed: {failed}/{len(tests)}")
    logger.info("")

    if failed == 0:
        logger.info("✅ All schema tests passed!")
        logger.info("MCP schemas are valid and can be serialized to JSON.")
        return 0
    else:
        logger.error(f"❌ {failed} test(s) failed")
        return 1


def main() -> int:
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="MCP Schema Smoke Test (Hermetic)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This test validates MCP schemas WITHOUT network access.
It tests schema validation, JSON serialization, and type safety.

Examples:
    python scripts/mcp_smoke.py
    python scripts/mcp_smoke.py --verbose
        """,
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        return run_all_tests(verbose=args.verbose)
    except KeyboardInterrupt:
        logger.info("\n🛑 Test interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"\n❌ Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
