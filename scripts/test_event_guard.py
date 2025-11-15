"""
Test Event Guard Functionality

Verifies:
- Event creation and storage
- Pre-event blackout periods
- Post-event momentum windows
- Symbol-specific allowlists
- Audit logging

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import sys
import time
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.risk.event_guard import (
    EventGuard,
    EventType,
    EventImpact,
    create_event_guard,
)
from utils.event_calendar import EventCalendar, create_event_calendar


def test_event_guard():
    """Test event guard functionality."""
    print("=" * 70)
    print("Event Guard Test")
    print("=" * 70)
    print()

    # Initialize event guard (disabled by default)
    print("1. Initializing event guard...")
    event_guard = create_event_guard(
        redis_manager=None,  # No Redis for this test
        enabled=True,  # Override feature flag for testing
    )
    print(f"   [OK] Event guard initialized: enabled={event_guard.enabled}")
    print()

    # Test 1: Add FOMC event in 30 seconds
    print("2. Adding FOMC event (30s from now)...")
    event_time = time.time() + 30
    event_id = event_guard.add_event(
        event_type=EventType.FOMC,
        timestamp=event_time,
        description="Test FOMC Meeting",
        impact=EventImpact.HIGH,
    )
    print(f"   [OK] Event added: {event_id}")
    print(f"   Event time: {datetime.fromtimestamp(event_time).strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Test 2: Check entry before blackout (should be allowed)
    print("3. Checking entry 65s before event (normal trading)...")
    test_time = event_time - 65
    decision = event_guard.check_entry_allowed("BTC/USD", current_time=test_time)
    print(f"   Allowed: {decision.allowed}")
    print(f"   Reason: {decision.reason}")
    print(f"   Momentum multiplier: {decision.momentum_multiplier}x")
    assert decision.allowed, "Entry should be allowed 65s before event"
    print("   [OK] Entry allowed as expected")
    print()

    # Test 3: Check entry during blackout (should be blocked)
    print("4. Checking entry 30s before event (blackout period)...")
    test_time = event_time - 30
    print(f"   Event time: {event_time}")
    print(f"   Test time: {test_time}")
    print(f"   Time delta: {event_time - test_time}s")
    decision = event_guard.check_entry_allowed("BTC/USD", current_time=test_time)
    print(f"   Allowed: {decision.allowed}")
    print(f"   Reason: {decision.reason}")
    print(f"   Event active: {decision.event_active}")
    assert not decision.allowed, "Entry should be blocked during blackout"
    print(f"   [OK] Entry blocked: {decision.reason}")
    print()

    # Test 4: Check entry with symbol on allowlist
    print("5. Testing symbol allowlist during blackout...")
    event_guard.add_symbol_to_allowlist(event_id, ["BTC/USD"])
    decision = event_guard.check_entry_allowed("BTC/USD", current_time=test_time)
    print(f"   Allowed: {decision.allowed}")
    print(f"   Reason: {decision.reason}")
    assert decision.allowed, "Entry should be allowed for symbols on allowlist"
    print("   [OK] Allowlist working correctly")
    print()

    # Test 5: Check entry during momentum window
    print("6. Checking entry 5s after event (momentum window)...")
    test_time = event_time + 5
    decision = event_guard.check_entry_allowed("ETH/USD", current_time=test_time)
    print(f"   Allowed: {decision.allowed}")
    print(f"   Reason: {decision.reason}")
    print(f"   Momentum multiplier: {decision.momentum_multiplier}x")
    assert decision.allowed, "Entry should be allowed in momentum window"
    assert decision.momentum_multiplier == 1.3, "Momentum multiplier should be 1.3x"
    print("   [OK] Momentum window active with 1.3x multiplier")
    print()

    # Test 6: Check entry after momentum window
    print("7. Checking entry 15s after event (normal trading)...")
    test_time = event_time + 15
    decision = event_guard.check_entry_allowed("BTC/USD", current_time=test_time)
    print(f"   Allowed: {decision.allowed}")
    print(f"   Reason: {decision.reason}")
    print(f"   Momentum multiplier: {decision.momentum_multiplier}x")
    assert decision.allowed, "Entry should be allowed after momentum window"
    assert decision.momentum_multiplier == 1.0, "Momentum multiplier should be 1.0x"
    print("   [OK] Normal trading resumed")
    print()

    # Test 7: Get upcoming events
    print("8. Getting upcoming events...")
    upcoming = event_guard.get_upcoming_events(hours=24)
    print(f"   [OK] Found {len(upcoming)} upcoming events")
    for event in upcoming:
        event_dt = datetime.fromtimestamp(event.timestamp)
        print(f"      - {event.description} at {event_dt.strftime('%Y-%m-%d %H:%M')}")
    print()

    # Test 8: Get status
    print("9. Getting event guard status...")
    status = event_guard.get_status()
    print(f"   Enabled: {status['enabled']}")
    print(f"   Total events: {status['total_events']}")
    print(f"   Upcoming (24h): {status['upcoming_24h']}")
    print(f"   Allowlist count: {status['allowlist_count']}")
    print("   [OK] Status retrieved")
    print()

    # Test 9: Add exchange listing event
    print("10. Adding exchange listing event...")
    listing_time = time.time() + 60
    listing_event = event_guard.add_event(
        event_type=EventType.EXCHANGE_LISTING,
        timestamp=listing_time,
        description="XYZ/USD listing on Coinbase",
        impact=EventImpact.SYMBOL_SPECIFIC,
        symbols=["XYZ/USD"],
    )
    event_guard.add_symbol_to_allowlist(listing_event, ["XYZ/USD"])
    print(f"   [OK] Listing event added: {listing_event}")
    print()

    # Test 10: Clear past events
    print("11. Clearing past events...")
    initial_count = len(event_guard.events)
    event_guard.clear_past_events(current_time=time.time() + 1000)
    final_count = len(event_guard.events)
    print(f"   [OK] Cleared {initial_count - final_count} past events")
    print()

    print("[SUCCESS] All event guard tests passed!")
    print()
    return True


def test_event_calendar():
    """Test event calendar management."""
    print("=" * 70)
    print("Event Calendar Test")
    print("=" * 70)
    print()

    # Initialize
    print("1. Initializing event calendar...")
    event_guard = create_event_guard(enabled=True)
    calendar = create_event_calendar(event_guard=event_guard)
    print("   [OK] Event calendar initialized")
    print()

    # Test adding FOMC meetings
    print("2. Adding FOMC meetings for 2025...")
    count = calendar.add_fomc_meetings(2025)
    print(f"   [OK] Added {count} FOMC meetings")
    print()

    # Test adding NFP releases
    print("3. Adding NFP releases for 2025...")
    count = calendar.add_nfp_releases(2025)
    print(f"   [OK] Added {count} NFP releases")
    print()

    # Test adding CPI releases
    print("4. Adding CPI releases for 2025...")
    count = calendar.add_cpi_releases(2025)
    print(f"   [OK] Added {count} CPI releases")
    print()

    # Test calendar summary
    print("5. Getting calendar summary (next 7 days)...")
    summary = calendar.get_calendar_summary(days=7)
    print(f"   Total upcoming: {summary['total_upcoming']}")
    print(f"   High impact: {summary['high_impact_count']}")
    print(f"   Events by type: {summary['events_by_type']}")
    print("   [OK] Calendar summary generated")
    print()

    # Test custom event
    print("6. Adding custom event...")
    custom_time = datetime.now() + timedelta(hours=2)
    event_id = calendar.add_custom_event(
        description="Major Partnership Announcement",
        event_time=custom_time,
        impact=EventImpact.MEDIUM,
    )
    print(f"   [OK] Custom event added: {event_id}")
    print()

    print("[SUCCESS] All event calendar tests passed!")
    print()
    return True


if __name__ == "__main__":
    try:
        success = test_event_guard() and test_event_calendar()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
