"""
Event Guard - Trading Protection Around Major Macro Events

Implements trading restrictions around high-impact events:
- 60s pre-event blackout: Disable new entries
- 10s post-event window: Allow momentum trades with size multiplier (≤1.3x)
- Symbol-specific allowlist for exchange listing events

Feature Flag: EVENTS_TRADING_ENABLED=false (default)

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, asdict


class EventType(Enum):
    """Types of market events."""
    FED_ANNOUNCEMENT = "fed_announcement"
    NFP = "nonfarm_payroll"
    CPI = "cpi_report"
    FOMC = "fomc_meeting"
    GDP = "gdp_release"
    RETAIL_SALES = "retail_sales"
    EXCHANGE_LISTING = "exchange_listing"
    HALVING = "halving"
    FORK = "fork"
    CUSTOM = "custom"


class EventImpact(Enum):
    """Event impact levels."""
    HIGH = "high"      # Major macro events (FED, FOMC)
    MEDIUM = "medium"  # Secondary indicators (retail sales)
    LOW = "low"        # Minor events
    SYMBOL_SPECIFIC = "symbol_specific"  # Listing events, etc.


@dataclass
class Event:
    """Market event definition."""
    event_id: str
    event_type: EventType
    impact: EventImpact
    timestamp: float  # Unix timestamp
    description: str
    symbols: Optional[List[str]] = None  # For symbol-specific events
    metadata: Optional[Dict] = None


@dataclass
class EventGuardDecision:
    """Decision from event guard."""
    allowed: bool
    reason: str
    event_active: Optional[Event] = None
    momentum_multiplier: float = 1.0  # Size multiplier for post-event momentum
    blackout_until: Optional[float] = None
    momentum_until: Optional[float] = None


class EventGuard:
    """
    Event guard for trading restrictions around major events.

    Blackout Periods:
    - 60s before high-impact event: No new entries
    - 10s after event: Momentum window with 1.3x size multiplier

    Symbol-Specific:
    - Exchange listings: Per-symbol allowlist
    """

    def __init__(
        self,
        redis_manager=None,
        logger=None,
        enabled: bool = None,
        pre_event_blackout: int = 60,
        post_event_momentum_window: int = 10,
        momentum_multiplier: float = 1.3,
    ):
        """
        Initialize event guard.

        Args:
            redis_manager: Redis client for event storage
            logger: Logger instance
            enabled: Override feature flag (default: from env)
            pre_event_blackout: Seconds before event to disable entries (default: 60)
            post_event_momentum_window: Seconds after event for momentum (default: 10)
            momentum_multiplier: Size multiplier for momentum window (default: 1.3)
        """
        self.redis = redis_manager
        self.logger = logger or logging.getLogger(__name__)

        # Feature flag
        if enabled is None:
            self.enabled = os.getenv("EVENTS_TRADING_ENABLED", "false").lower() == "true"
        else:
            self.enabled = enabled

        # Configuration
        self.pre_event_blackout = pre_event_blackout
        self.post_event_momentum_window = post_event_momentum_window
        self.momentum_multiplier = min(momentum_multiplier, 1.3)  # Cap at 1.3x

        # In-memory event cache
        self.events: List[Event] = []
        self.symbol_allowlist: Dict[str, List[str]] = {}  # event_id -> [symbols]

        # Audit log
        self.audit_log_enabled = os.getenv("EVENT_GUARD_AUDIT_LOG", "true").lower() == "true"

        if not self.enabled:
            self.logger.info("EventGuard disabled (EVENTS_TRADING_ENABLED=false)")
        else:
            self.logger.info(
                f"EventGuard enabled: "
                f"blackout={pre_event_blackout}s, "
                f"momentum={post_event_momentum_window}s @ {momentum_multiplier}x"
            )

    def add_event(
        self,
        event_type: EventType,
        timestamp: float,
        description: str,
        impact: EventImpact = EventImpact.HIGH,
        symbols: Optional[List[str]] = None,
        event_id: Optional[str] = None,
    ) -> str:
        """
        Add event to calendar.

        Args:
            event_type: Type of event
            timestamp: Unix timestamp of event
            description: Event description
            impact: Event impact level
            symbols: Symbol-specific (for listing events)
            event_id: Optional custom event ID

        Returns:
            Event ID
        """
        if event_id is None:
            event_id = f"{event_type.value}_{int(timestamp)}"

        event = Event(
            event_id=event_id,
            event_type=event_type,
            impact=impact,
            timestamp=timestamp,
            description=description,
            symbols=symbols,
        )

        # Add to in-memory cache
        self.events.append(event)

        # Store in Redis if available
        if self.redis:
            try:
                event_data = {
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "impact": event.impact.value,
                    "timestamp": event.timestamp,
                    "description": event.description,
                }
                if symbols:
                    event_data["symbols"] = ",".join(symbols)

                self.redis.publish_event("events:calendar", event_data)
                self.logger.info(f"Event added: {event_id} at {datetime.fromtimestamp(timestamp)}")
            except Exception as e:
                self.logger.error(f"Error storing event in Redis: {e}")

        # Audit log
        if self.audit_log_enabled:
            self._audit_log("EVENT_ADDED", event_id, {
                "type": event_type.value,
                "timestamp": timestamp,
                "impact": impact.value,
            })

        return event_id

    def add_symbol_to_allowlist(self, event_id: str, symbols: List[str]):
        """
        Add symbols to event allowlist.

        For exchange listing events, these symbols are allowed to trade
        even during blackout periods.

        Args:
            event_id: Event identifier
            symbols: List of symbols to allow
        """
        if event_id not in self.symbol_allowlist:
            self.symbol_allowlist[event_id] = []

        self.symbol_allowlist[event_id].extend(symbols)
        self.logger.info(f"Added symbols to allowlist for {event_id}: {symbols}")

        # Audit log
        if self.audit_log_enabled:
            self._audit_log("ALLOWLIST_UPDATED", event_id, {
                "symbols": symbols,
            })

    def check_entry_allowed(
        self,
        symbol: str,
        current_time: Optional[float] = None,
    ) -> EventGuardDecision:
        """
        Check if new entry is allowed for symbol.

        Args:
            symbol: Trading symbol
            current_time: Current timestamp (default: now)

        Returns:
            EventGuardDecision with allowed status and reason
        """
        if not self.enabled:
            return EventGuardDecision(
                allowed=True,
                reason="Event guard disabled",
                momentum_multiplier=1.0,
            )

        if current_time is None:
            current_time = time.time()

        # Check for active events
        active_event, time_delta = self._get_nearest_event(current_time)

        if active_event is None:
            return EventGuardDecision(
                allowed=True,
                reason="No upcoming events",
                momentum_multiplier=1.0,
            )

        # Pre-event blackout period (event is upcoming, within blackout window)
        if 0 < time_delta <= self.pre_event_blackout:
            # Check if symbol is on allowlist
            if self._is_symbol_allowed(active_event.event_id, symbol):
                decision = EventGuardDecision(
                    allowed=True,
                    reason=f"Symbol on allowlist for {active_event.description}",
                    event_active=active_event,
                    momentum_multiplier=1.0,
                )
            else:
                decision = EventGuardDecision(
                    allowed=False,
                    reason=f"Pre-event blackout: {active_event.description} in {time_delta:.0f}s",
                    event_active=active_event,
                    blackout_until=active_event.timestamp,
                )

            # Audit log
            if self.audit_log_enabled:
                self._audit_log("ENTRY_CHECK", symbol, {
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "event": active_event.event_id,
                    "time_delta": time_delta,
                })

            return decision

        # Post-event momentum window (event just happened, within momentum window)
        if -self.post_event_momentum_window <= time_delta <= 0:
            decision = EventGuardDecision(
                allowed=True,
                reason=f"Post-event momentum window: {active_event.description}",
                event_active=active_event,
                momentum_multiplier=self.momentum_multiplier,
                momentum_until=active_event.timestamp + self.post_event_momentum_window,
            )

            # Audit log
            if self.audit_log_enabled:
                self._audit_log("MOMENTUM_WINDOW", symbol, {
                    "multiplier": self.momentum_multiplier,
                    "event": active_event.event_id,
                    "time_delta": time_delta,
                })

            return decision

        # During event (0-10s) - default to allowed
        if time_delta == 0:
            return EventGuardDecision(
                allowed=True,
                reason=f"Event in progress: {active_event.description}",
                event_active=active_event,
                momentum_multiplier=1.0,
            )

        # Normal trading
        return EventGuardDecision(
            allowed=True,
            reason="Normal trading - no active events",
            momentum_multiplier=1.0,
        )

    def get_upcoming_events(
        self,
        hours: int = 24,
        current_time: Optional[float] = None,
    ) -> List[Event]:
        """
        Get upcoming events in next N hours.

        Args:
            hours: Lookahead window in hours
            current_time: Current timestamp (default: now)

        Returns:
            List of upcoming events
        """
        if current_time is None:
            current_time = time.time()

        cutoff = current_time + (hours * 3600)

        upcoming = [
            event for event in self.events
            if current_time <= event.timestamp <= cutoff
        ]

        return sorted(upcoming, key=lambda e: e.timestamp)

    def remove_event(self, event_id: str) -> bool:
        """
        Remove event from calendar.

        Args:
            event_id: Event identifier

        Returns:
            True if removed, False if not found
        """
        initial_count = len(self.events)
        self.events = [e for e in self.events if e.event_id != event_id]

        removed = len(self.events) < initial_count

        if removed:
            self.logger.info(f"Event removed: {event_id}")

            # Remove from allowlist
            if event_id in self.symbol_allowlist:
                del self.symbol_allowlist[event_id]

            # Audit log
            if self.audit_log_enabled:
                self._audit_log("EVENT_REMOVED", event_id, {})

        return removed

    def clear_past_events(self, current_time: Optional[float] = None):
        """
        Remove events that have passed.

        Args:
            current_time: Current timestamp (default: now)
        """
        if current_time is None:
            current_time = time.time()

        # Keep events within momentum window (for logging)
        cutoff = current_time - self.post_event_momentum_window

        initial_count = len(self.events)
        self.events = [e for e in self.events if e.timestamp >= cutoff]

        removed = initial_count - len(self.events)
        if removed > 0:
            self.logger.info(f"Cleared {removed} past events")

    def _get_nearest_event(
        self,
        current_time: float,
    ) -> Tuple[Optional[Event], float]:
        """
        Get nearest event within blackout/momentum window.

        Args:
            current_time: Current timestamp

        Returns:
            (Event, time_delta) where time_delta = event_time - current_time
            None if no events within relevant window
        """
        if not self.events:
            return None, 0.0

        # Check each event to see if it's within our care window
        # Care window: from (momentum_window before) to (blackout_window after)
        relevant_events = []

        for event in self.events:
            time_delta = event.timestamp - current_time

            # Check if event is within blackout or momentum window
            # Blackout: 0 < delta <= blackout_seconds (event is upcoming, within blackout)
            # Momentum: -momentum_seconds <= delta <= 0 (event just happened, within momentum)
            in_blackout = 0 < time_delta <= self.pre_event_blackout
            in_momentum = -self.post_event_momentum_window <= time_delta <= 0

            if in_blackout or in_momentum:
                relevant_events.append((event, time_delta))

        if not relevant_events:
            return None, 0.0

        # Return event with smallest absolute time delta (nearest to current time)
        nearest_event, nearest_delta = min(
            relevant_events,
            key=lambda x: abs(x[1])
        )

        return nearest_event, nearest_delta

    def _is_symbol_allowed(self, event_id: str, symbol: str) -> bool:
        """
        Check if symbol is on allowlist for event.

        Args:
            event_id: Event identifier
            symbol: Trading symbol

        Returns:
            True if allowed, False otherwise
        """
        if event_id not in self.symbol_allowlist:
            return False

        return symbol in self.symbol_allowlist[event_id]

    def _audit_log(self, action: str, subject: str, metadata: Dict):
        """
        Write audit log entry.

        Args:
            action: Action type
            subject: Subject (symbol, event_id, etc.)
            metadata: Additional data
        """
        log_entry = {
            "timestamp": time.time(),
            "action": action,
            "subject": subject,
            "metadata": metadata,
        }

        # Log to file
        self.logger.info(f"AUDIT: {action} - {subject} - {metadata}")

        # Publish to Redis if available
        if self.redis:
            try:
                self.redis.publish_event("events:audit_log", log_entry)
            except Exception as e:
                self.logger.error(f"Error publishing audit log: {e}")

    def get_status(self) -> Dict:
        """
        Get event guard status.

        Returns:
            Status dictionary
        """
        current_time = time.time()
        upcoming = self.get_upcoming_events(hours=24, current_time=current_time)

        active_event, time_delta = self._get_nearest_event(current_time)

        status = {
            "enabled": self.enabled,
            "total_events": len(self.events),
            "upcoming_24h": len(upcoming),
            "active_event": None,
            "in_blackout": False,
            "in_momentum_window": False,
            "allowlist_count": len(self.symbol_allowlist),
        }

        if active_event:
            status["active_event"] = {
                "event_id": active_event.event_id,
                "type": active_event.event_type.value,
                "description": active_event.description,
                "timestamp": active_event.timestamp,
                "time_delta": time_delta,
            }

            if -self.pre_event_blackout <= time_delta < 0:
                status["in_blackout"] = True
            elif 0 <= time_delta <= self.post_event_momentum_window:
                status["in_momentum_window"] = True

        return status


# Convenience function for easy integration
def create_event_guard(
    redis_manager=None,
    logger=None,
    enabled: bool = None,
) -> EventGuard:
    """
    Create and configure event guard.

    Args:
        redis_manager: Redis client
        logger: Logger instance
        enabled: Override feature flag

    Returns:
        EventGuard instance
    """
    return EventGuard(
        redis_manager=redis_manager,
        logger=logger,
        enabled=enabled,
    )
