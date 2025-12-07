"""
Mode-aware stream configuration for crypto-ai-bot.

Provides functions to get the correct Redis stream names based on ENGINE_MODE (paper vs live).
This ensures complete separation between paper/backtest and live trading data.

Usage:
    from config.mode_aware_streams import get_signal_stream, get_pnl_stream, get_engine_mode

    # Get the correct stream based on ENGINE_MODE env var
    signal_stream = get_signal_stream()  # Returns "signals:paper" or "signals:live"
    pnl_stream = get_pnl_stream()        # Returns "pnl:paper" or "pnl:live"
"""

import os
from typing import Literal
from .stream_registry import get_stream

# Type alias for engine modes
EngineMode = Literal["paper", "live"]


def get_engine_mode() -> EngineMode:
    """
    Get the current engine mode from environment variable.

    Returns:
        "paper" or "live" based on ENGINE_MODE env var

    Defaults to "paper" if ENGINE_MODE is not set (safety measure).
    """
    mode = os.getenv("ENGINE_MODE", "paper").lower()

    if mode not in ("paper", "live"):
        raise ValueError(
            f"Invalid ENGINE_MODE='{mode}'. Must be 'paper' or 'live'. "
            f"Defaulting to 'paper' for safety."
        )

    return mode  # type: ignore


def get_signal_stream(mode: EngineMode = None) -> str:
    """
    Get the signal stream name for the current or specified mode.

    Args:
        mode: Override the ENGINE_MODE env var. If None, uses get_engine_mode()

    Returns:
        "signals:paper" for paper mode
        "signals:live" for live mode

    Examples:
        >>> os.environ["ENGINE_MODE"] = "paper"
        >>> get_signal_stream()
        'signals:paper'

        >>> get_signal_stream(mode="live")
        'signals:live'
    """
    if mode is None:
        mode = get_engine_mode()

    stream_key = f"signals_{mode}"
    return get_stream(stream_key)


def get_pnl_stream(mode: EngineMode = None) -> str:
    """
    Get the PnL stream name for the current or specified mode.

    Args:
        mode: Override the ENGINE_MODE env var. If None, uses get_engine_mode()

    Returns:
        "pnl:paper" for paper mode
        "pnl:live" for live mode

    Examples:
        >>> os.environ["ENGINE_MODE"] = "live"
        >>> get_pnl_stream()
        'pnl:live'
    """
    if mode is None:
        mode = get_engine_mode()

    stream_key = f"pnl_{mode}"
    return get_stream(stream_key)


def get_equity_stream(mode: EngineMode = None) -> str:
    """
    Get the equity curve stream name for the current or specified mode.

    Args:
        mode: Override the ENGINE_MODE env var. If None, uses get_engine_mode()

    Returns:
        "pnl:paper:equity_curve" for paper mode
        "pnl:live:equity_curve" for live mode
    """
    if mode is None:
        mode = get_engine_mode()

    stream_key = f"equity_{mode}"
    return get_stream(stream_key)


def get_all_mode_streams(mode: EngineMode = None) -> dict:
    """
    Get all mode-aware stream names for the current or specified mode.

    Args:
        mode: Override the ENGINE_MODE env var. If None, uses get_engine_mode()

    Returns:
        Dictionary with stream types as keys and stream names as values

    Example:
        >>> os.environ["ENGINE_MODE"] = "paper"
        >>> get_all_mode_streams()
        {
            'signals': 'signals:paper',
            'pnl': 'pnl:paper',
            'equity_curve': 'pnl:paper:equity_curve',
            'mode': 'paper'
        }
    """
    if mode is None:
        mode = get_engine_mode()

    return {
        "signals": get_signal_stream(mode),
        "pnl": get_pnl_stream(mode),
        "equity_curve": get_equity_stream(mode),
        "mode": mode,
    }


def validate_mode_separation(signal_data: dict) -> None:
    """
    Validate that signal data doesn't accidentally mix paper and live modes.

    Args:
        signal_data: Signal dictionary to validate

    Raises:
        ValueError: If mode mismatch detected

    This is a safety check to prevent accidentally publishing paper signals
    to live streams or vice versa.
    """
    current_mode = get_engine_mode()

    # Check if signal has a mode indicator
    signal_mode = signal_data.get("mode") or signal_data.get("trading_mode")

    if signal_mode and signal_mode.lower() != current_mode:
        raise ValueError(
            f"Mode mismatch! ENGINE_MODE={current_mode} but signal has mode={signal_mode}. "
            f"This prevents accidental cross-contamination between paper and live streams."
        )


# Convenience exports
__all__ = [
    "get_engine_mode",
    "get_signal_stream",
    "get_pnl_stream",
    "get_equity_stream",
    "get_all_mode_streams",
    "validate_mode_separation",
    "EngineMode",
]
