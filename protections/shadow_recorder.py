"""
ShadowOrderRecorder - Audit Trail for Shadow Execution Mode

Records shadow order events with complete audit trail:
- timestamp (ISO 8601)
- symbol
- side (buy/sell)
- size
- price
- notional_usd
- reason (why order was generated)
- risk_check_outcome (passed/failed + details)
- gate_outcome (allowed/blocked + gate name)
- shadow_order_id

Shadow orders:
1. Generate the exact same order intents as live
2. Run ALL risk checks
3. Record detailed audit events
4. NEVER call Kraken private endpoints

Usage:
    from protections.shadow_recorder import ShadowOrderRecorder, get_shadow_recorder

    recorder = get_shadow_recorder()

    # Record a shadow order
    event = recorder.record_shadow_order(
        order_request=order_request,
        gate_result=gate_result,
        risk_check_result=risk_result,
        reason="scalp_signal",
    )

    # Get audit trail
    events = recorder.get_recent_events(limit=100)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)


# =============================================================================
# SHADOW ORDER EVENT
# =============================================================================

@dataclass
class ShadowOrderEvent:
    """Complete audit record for a shadow order."""

    # Identifiers
    shadow_order_id: str
    client_order_id: Optional[str] = None

    # Timing
    timestamp: str = ""  # ISO 8601 format
    timestamp_unix: float = 0.0

    # Order details
    symbol: str = ""
    side: str = ""
    order_type: str = "limit"
    size: float = 0.0
    price: Optional[float] = None
    notional_usd: float = 0.0

    # Signal/reason
    reason: str = "unknown"  # Why this order was generated (e.g., "scalp_signal", "rebalance")

    # Risk check outcome
    risk_check_passed: bool = True
    risk_check_details: Dict[str, Any] = field(default_factory=dict)

    # Gate outcome
    gate_allowed: bool = True
    gate_name: Optional[str] = None  # Which gate was hit (if blocked)
    gate_reason: Optional[str] = None

    # Execution outcome
    execution_mode: str = "shadow"  # "shadow", "dry_run", "live"
    would_execute: bool = True  # Would this have executed if live?

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def to_log_line(self) -> str:
        """Format as a single log line for audit trail."""
        return (
            f"SHADOW_AUDIT | {self.timestamp} | {self.shadow_order_id} | "
            f"{self.side.upper()} {self.size} {self.symbol} @ {self.price} | "
            f"notional=${self.notional_usd:.2f} | "
            f"reason={self.reason} | "
            f"risk={('PASS' if self.risk_check_passed else 'FAIL')} | "
            f"gate={('ALLOW' if self.gate_allowed else f'BLOCK:{self.gate_name}')} | "
            f"would_execute={self.would_execute}"
        )


# =============================================================================
# SHADOW ORDER RECORDER
# =============================================================================

class ShadowOrderRecorder:
    """
    Records and manages shadow order audit trail.

    Features:
    - In-memory event buffer (configurable size)
    - Structured logging for audit compliance
    - Optional Redis stream publishing (if configured)
    - JSON export for analysis
    """

    def __init__(
        self,
        max_events: int = 1000,
        redis_client: Optional[Any] = None,
        stream_name: str = "shadow:orders:audit",
    ):
        """
        Initialize the shadow order recorder.

        Args:
            max_events: Maximum events to keep in memory
            redis_client: Optional Redis client for stream publishing
            stream_name: Redis stream name for audit events
        """
        self.logger = logging.getLogger(f"{__name__}.ShadowOrderRecorder")
        self._events: deque = deque(maxlen=max_events)
        self._redis_client = redis_client
        self._stream_name = stream_name
        self._event_count = 0

    def record_shadow_order(
        self,
        shadow_order_id: str,
        symbol: str,
        side: str,
        size: float,
        price: Optional[float],
        order_type: str = "limit",
        client_order_id: Optional[str] = None,
        reason: str = "unknown",
        risk_check_passed: bool = True,
        risk_check_details: Optional[Dict[str, Any]] = None,
        gate_allowed: bool = True,
        gate_name: Optional[str] = None,
        gate_reason: Optional[str] = None,
    ) -> ShadowOrderEvent:
        """
        Record a shadow order event with complete audit trail.

        Args:
            shadow_order_id: Unique ID for this shadow order
            symbol: Trading pair (e.g., "BTC/USD")
            side: Order side ("buy" or "sell")
            size: Order size
            price: Order price (None for market orders)
            order_type: Order type ("limit", "market")
            client_order_id: Client-provided order ID
            reason: Why this order was generated
            risk_check_passed: Whether risk checks passed
            risk_check_details: Details of risk check results
            gate_allowed: Whether execution gate allowed the order
            gate_name: Name of gate that blocked (if blocked)
            gate_reason: Reason for gate block

        Returns:
            ShadowOrderEvent with complete audit data
        """
        now = datetime.now(timezone.utc)
        notional_usd = float(size) * float(price or 0)

        event = ShadowOrderEvent(
            shadow_order_id=shadow_order_id,
            client_order_id=client_order_id,
            timestamp=now.isoformat(),
            timestamp_unix=now.timestamp(),
            symbol=symbol,
            side=side,
            order_type=order_type,
            size=float(size),
            price=float(price) if price else None,
            notional_usd=notional_usd,
            reason=reason,
            risk_check_passed=risk_check_passed,
            risk_check_details=risk_check_details or {},
            gate_allowed=gate_allowed,
            gate_name=gate_name,
            gate_reason=gate_reason,
            execution_mode="shadow",
            would_execute=risk_check_passed and gate_allowed,
        )

        # Store in memory
        self._events.append(event)
        self._event_count += 1

        # Log the audit trail
        self.logger.info(event.to_log_line())

        # Publish to Redis stream if available
        self._publish_to_stream(event)

        return event

    def _publish_to_stream(self, event: ShadowOrderEvent) -> None:
        """Publish event to Redis stream for persistence."""
        if not self._redis_client:
            return

        try:
            # Flatten the event for Redis stream
            stream_data = {
                "shadow_order_id": event.shadow_order_id,
                "timestamp": event.timestamp,
                "symbol": event.symbol,
                "side": event.side,
                "size": str(event.size),
                "price": str(event.price) if event.price else "",
                "notional_usd": str(event.notional_usd),
                "reason": event.reason,
                "risk_check_passed": str(event.risk_check_passed),
                "gate_allowed": str(event.gate_allowed),
                "gate_name": event.gate_name or "",
                "would_execute": str(event.would_execute),
            }
            self._redis_client.xadd(
                self._stream_name,
                stream_data,
                maxlen=10000,  # Keep last 10k events
            )
        except Exception as e:
            self.logger.warning("Failed to publish shadow event to Redis: %s", e)

    def get_recent_events(self, limit: int = 100) -> List[ShadowOrderEvent]:
        """Get recent shadow order events."""
        events = list(self._events)
        return events[-limit:] if len(events) > limit else events

    def get_event_count(self) -> int:
        """Get total number of recorded events."""
        return self._event_count

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics of shadow orders."""
        events = list(self._events)
        if not events:
            return {
                "total_events": 0,
                "would_execute_count": 0,
                "blocked_count": 0,
                "total_notional_usd": 0,
            }

        would_execute = [e for e in events if e.would_execute]
        blocked = [e for e in events if not e.would_execute]

        return {
            "total_events": len(events),
            "would_execute_count": len(would_execute),
            "blocked_count": len(blocked),
            "total_notional_usd": sum(e.notional_usd for e in events),
            "symbols": list(set(e.symbol for e in events)),
            "block_reasons": list(set(e.gate_name for e in blocked if e.gate_name)),
        }

    def export_to_json(self, filepath: Optional[str] = None) -> str:
        """Export all events to JSON."""
        events = [e.to_dict() for e in self._events]
        json_str = json.dumps(events, indent=2, default=str)

        if filepath:
            with open(filepath, "w") as f:
                f.write(json_str)
            self.logger.info("Exported %d shadow events to %s", len(events), filepath)

        return json_str

    def clear(self) -> None:
        """Clear the event buffer (for testing)."""
        self._events.clear()
        self._event_count = 0


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_recorder_instance: Optional[ShadowOrderRecorder] = None


def get_shadow_recorder(
    redis_client: Optional[Any] = None,
) -> ShadowOrderRecorder:
    """
    Get or create the singleton ShadowOrderRecorder instance.

    Args:
        redis_client: Optional Redis client for stream publishing

    Returns:
        The global ShadowOrderRecorder instance
    """
    global _recorder_instance
    if _recorder_instance is None:
        _recorder_instance = ShadowOrderRecorder(redis_client=redis_client)
    return _recorder_instance


def reset_shadow_recorder() -> None:
    """Reset the singleton instance (for testing)."""
    global _recorder_instance
    _recorder_instance = None


__all__ = [
    "ShadowOrderEvent",
    "ShadowOrderRecorder",
    "get_shadow_recorder",
    "reset_shadow_recorder",
]
