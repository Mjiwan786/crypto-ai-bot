"""
Schema Mapper: ScalperSignal → SignalDTO
==========================================

Converts crypto-ai-bot's ScalperSignal schema to SignalDTO format
expected by signals-api and signals-site.

PURPOSE:
- Bridge the schema mismatch between bot and API
- Ensure signals flow correctly through the pipeline
- Maintain data integrity across system boundaries

FIELD MAPPINGS:
- symbol → pair (normalized: "BTC/USD" → "BTC-USD")
- ts_exchange → ts (use exchange timestamp as primary)
- model → strategy
- stop → sl (stop loss)
- (preserve: side, entry, tp, confidence)

USAGE:
    from signals.schema_mapper import map_scalper_to_signal_dto

    scalper_signal = create_scalper_signal(...)
    signal_dto = map_scalper_to_signal_dto(scalper_signal, mode="paper")
    # signal_dto is now compatible with signals-api
"""

from typing import Dict, Literal
import logging

from signals.scalper_schema import ScalperSignal
from models.signal_dto import generate_signal_id

logger = logging.getLogger(__name__)


def map_scalper_to_signal_dto(
    scalper_signal: ScalperSignal,
    mode: Literal["paper", "live"] = "paper"
) -> Dict:
    """
    Convert ScalperSignal to SignalDTO format for signals-api compatibility.

    This function bridges the schema gap between crypto-ai-bot's internal
    ScalperSignal schema and the SignalDTO contract used by signals-api.

    Field Transformations:
    ----------------------
    1. symbol → pair:
       - Normalize slash to hyphen ("BTC/USD" → "BTC-USD")
       - Ensure uppercase (already done by ScalperSignal validator)

    2. ts_exchange → ts:
       - Use exchange timestamp as the primary timestamp
       - This represents when the signal was generated at the source

    3. model → strategy:
       - Rename field for API compatibility

    4. stop → sl:
       - Rename "stop" to "sl" (stop loss) per SignalDTO schema

    5. Generate deterministic ID:
       - Use generate_signal_id(ts, pair, strategy) for idempotent IDs

    Args:
        scalper_signal: ScalperSignal from crypto-ai-bot
        mode: Trading mode ("paper" or "live")

    Returns:
        Dictionary compatible with SignalDTO schema

    Raises:
        ValueError: If mode is not "paper" or "live"

    Example:
        >>> from signals.scalper_schema import create_scalper_signal
        >>> scalper = create_scalper_signal(
        ...     symbol="BTC/USD",
        ...     timeframe="15s",
        ...     side="long",
        ...     entry=50000.0,
        ...     stop=49500.0,
        ...     tp=50500.0,
        ...     confidence=0.85,
        ...     model="momentum_v1"
        ... )
        >>> dto = map_scalper_to_signal_dto(scalper, mode="paper")
        >>> dto["pair"]
        'BTC-USD'
        >>> dto["strategy"]
        'momentum_v1'
    """
    # Validate mode
    if mode not in ["paper", "live"]:
        raise ValueError(f"Invalid mode: {mode}. Must be 'paper' or 'live'")

    # Normalize symbol: "BTC/USD" → "BTC-USD"
    pair = scalper_signal.symbol.replace("/", "-")

    # Use exchange timestamp as primary timestamp
    ts_ms = scalper_signal.ts_exchange

    # Map model to strategy
    strategy = scalper_signal.model

    # Generate deterministic signal ID
    signal_id = generate_signal_id(ts_ms, pair, strategy)

    # Build SignalDTO-compatible dictionary
    signal_dto = {
        "id": signal_id,
        "ts": ts_ms,
        "pair": pair,
        "side": scalper_signal.side,
        "entry": scalper_signal.entry,
        "sl": scalper_signal.stop,  # stop → sl
        "tp": scalper_signal.tp,
        "strategy": strategy,
        "confidence": scalper_signal.confidence,
        "mode": mode,
    }

    # Log the mapping for debugging
    logger.debug(
        f"Mapped ScalperSignal → SignalDTO: "
        f"{scalper_signal.symbol} → {pair}, "
        f"model={scalper_signal.model} → strategy={strategy}, "
        f"ts={ts_ms}"
    )

    return signal_dto


def get_unified_stream_key(mode: Literal["paper", "live"] = "paper") -> str:
    """
    Get unified Redis stream key for signals.

    Replaces per-symbol stream keys (signals:BTC-USD:15s) with
    unified mode-based streams (signals:paper or signals:live).

    This ensures compatibility with signals-api which expects
    all signals in a single stream per trading mode.

    Args:
        mode: Trading mode ("paper" or "live")

    Returns:
        Unified stream key (e.g., "signals:paper")

    Raises:
        ValueError: If mode is not "paper" or "live"

    Example:
        >>> get_unified_stream_key("paper")
        'signals:paper'
        >>> get_unified_stream_key("live")
        'signals:live'
    """
    if mode not in ["paper", "live"]:
        raise ValueError(f"Invalid mode: {mode}. Must be 'paper' or 'live'")

    return f"signals:{mode}"


# =============================================================================
# BACKWARD COMPATIBILITY
# =============================================================================

def validate_signal_dto_schema(signal_dto: Dict) -> bool:
    """
    Validate that a dictionary matches SignalDTO schema requirements.

    Checks for required fields and basic type validation.
    This is a lightweight validation; full validation happens
    in signals-api using Pydantic.

    Args:
        signal_dto: Dictionary to validate

    Returns:
        True if valid, False otherwise

    Example:
        >>> dto = map_scalper_to_signal_dto(scalper_signal)
        >>> validate_signal_dto_schema(dto)
        True
    """
    required_fields = {
        "id": str,
        "ts": int,
        "pair": str,
        "side": str,
        "entry": (int, float),
        "sl": (int, float),
        "tp": (int, float),
        "strategy": str,
        "confidence": (int, float),
        "mode": str,
    }

    try:
        for field, expected_type in required_fields.items():
            if field not in signal_dto:
                logger.error(f"Missing required field: {field}")
                return False

            if not isinstance(signal_dto[field], expected_type):
                logger.error(
                    f"Field '{field}' has wrong type: "
                    f"expected {expected_type}, got {type(signal_dto[field])}"
                )
                return False

        # Validate side
        if signal_dto["side"] not in ["long", "short"]:
            logger.error(f"Invalid side: {signal_dto['side']}")
            return False

        # Validate mode
        if signal_dto["mode"] not in ["paper", "live"]:
            logger.error(f"Invalid mode: {signal_dto['mode']}")
            return False

        # Validate confidence range
        if not (0.0 <= signal_dto["confidence"] <= 1.0):
            logger.error(f"Confidence out of range: {signal_dto['confidence']}")
            return False

        return True

    except Exception as e:
        logger.error(f"Validation error: {e}")
        return False


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "map_scalper_to_signal_dto",
    "get_unified_stream_key",
    "validate_signal_dto_schema",
]


# =============================================================================
# SELF-CHECK
# =============================================================================

if __name__ == "__main__":
    """Test schema mapper"""
    import sys
    from signals.scalper_schema import create_scalper_signal

    print("=" * 80)
    print(" " * 25 + "SCHEMA MAPPER TEST")
    print("=" * 80)

    # Test 1: Basic mapping
    print("\nTest 1: Map ScalperSignal to SignalDTO")
    try:
        scalper = create_scalper_signal(
            symbol="BTC/USD",
            timeframe="15s",
            side="long",
            entry=50000.0,
            stop=49500.0,
            tp=50500.0,
            confidence=0.85,
            model="momentum_v1"
        )

        dto = map_scalper_to_signal_dto(scalper, mode="paper")

        print(f"  Input symbol: {scalper.symbol}")
        print(f"  Output pair: {dto['pair']}")
        assert dto["pair"] == "BTC-USD", "Symbol normalization failed"

        print(f"  Input model: {scalper.model}")
        print(f"  Output strategy: {dto['strategy']}")
        assert dto["strategy"] == "momentum_v1", "Model mapping failed"

        print(f"  Input stop: {scalper.stop}")
        print(f"  Output sl: {dto['sl']}")
        assert dto["sl"] == 49500.0, "Stop loss mapping failed"

        print(f"  Mode: {dto['mode']}")
        assert dto["mode"] == "paper", "Mode setting failed"

        print("  [PASS] All field mappings correct")

    except Exception as e:
        print(f"  [FAIL] {e}")
        sys.exit(1)

    # Test 2: Unified stream key
    print("\nTest 2: Get unified stream key")
    try:
        paper_stream = get_unified_stream_key("paper")
        live_stream = get_unified_stream_key("live")

        print(f"  Paper stream: {paper_stream}")
        print(f"  Live stream: {live_stream}")

        assert paper_stream == "signals:paper", "Paper stream key wrong"
        assert live_stream == "signals:live", "Live stream key wrong"

        print("  [PASS] Stream keys correct")

    except Exception as e:
        print(f"  [FAIL] {e}")
        sys.exit(1)

    # Test 3: Schema validation
    print("\nTest 3: Validate SignalDTO schema")
    try:
        valid = validate_signal_dto_schema(dto)
        assert valid, "Valid schema marked as invalid"
        print("  [PASS] Valid schema accepted")

        # Test invalid schema
        invalid_dto = dto.copy()
        del invalid_dto["pair"]
        valid = validate_signal_dto_schema(invalid_dto)
        assert not valid, "Invalid schema marked as valid"
        print("  [PASS] Invalid schema rejected")

    except Exception as e:
        print(f"  [FAIL] {e}")
        sys.exit(1)

    # Test 4: Multiple symbols
    print("\nTest 4: Map multiple symbols")
    try:
        symbols = ["BTC/USD", "ETH/USD", "SOL/USD"]
        for symbol in symbols:
            scalper = create_scalper_signal(
                symbol=symbol,
                timeframe="15s",
                side="long",
                entry=1000.0,
                stop=990.0,
                tp=1010.0,
                confidence=0.75,
                model="test_v1"
            )
            dto = map_scalper_to_signal_dto(scalper, mode="paper")
            expected_pair = symbol.replace("/", "-")
            assert dto["pair"] == expected_pair, f"Symbol {symbol} mapping failed"
            print(f"  {symbol} -> {dto['pair']} [OK]")

        print("  [PASS] Multi-symbol mapping works")

    except Exception as e:
        print(f"  [FAIL] {e}")
        sys.exit(1)

    print("\n" + "=" * 80)
    print("[PASS] All tests PASSED (4/4)")
    print("=" * 80)
