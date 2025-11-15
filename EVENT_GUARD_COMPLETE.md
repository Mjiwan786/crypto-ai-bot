# Event Guard System - COMPLETE ✅

## Summary

Successfully implemented a comprehensive event guard system that protects trading around major macro events with blackout periods and momentum windows.

**Status:** ✅ PRODUCTION READY
**Date:** 2025-11-08

---

## What Was Delivered

### 1. Core Event Guard Module ✅

**File:** `agents/risk/event_guard.py` (467 lines)

**Features:**
- Pre-event blackout periods (60s before major events - no new entries)
- Post-event momentum windows (10s after events - 1.3x size multiplier)
- Symbol-specific allowlists for exchange listings
- Event calendar management with multiple event types
- Audit logging for all decisions
- Feature flag control: `EVENTS_TRADING_ENABLED=false` (disabled by default)

**Event Types Supported:**
```python
EventType:
  - FED_ANNOUNCEMENT
  - FOMC (Federal Open Market Committee)
  - NFP (Non-Farm Payroll)
  - CPI (Consumer Price Index)
  - GDP_RELEASE
  - RETAIL_SALES
  - EXCHANGE_LISTING
  - HALVING (Bitcoin halving)
  - FORK (Blockchain forks)
  - CUSTOM (User-defined events)
```

**Impact Levels:**
```python
EventImpact:
  - HIGH: Major market movers (60s blackout)
  - MEDIUM: Secondary indicators (customizable)
  - LOW: Minor events (monitoring only)
  - SYMBOL_SPECIFIC: Affects specific symbols only
```

**Key Methods:**
```python
# Check if entry is allowed
decision = event_guard.check_entry_allowed(
    symbol="BTC/USD",
    current_time=time.time(),
)

# Add event to calendar
event_id = event_guard.add_event(
    event_type=EventType.FOMC,
    timestamp=event_timestamp,
    description="FOMC Meeting - March 2025",
    impact=EventImpact.HIGH,
)

# Add symbol to allowlist
event_guard.add_symbol_to_allowlist(
    event_id=event_id,
    symbols=["BTC/USD", "ETH/USD"],
)
```

---

### 2. Event Calendar Management ✅

**File:** `utils/event_calendar.py` (383 lines)

**Features:**
- Automated FOMC meeting scheduling
- Non-Farm Payroll (NFP) scheduling (first Friday of each month)
- CPI report scheduling
- Exchange listing event management
- Custom event creation
- Calendar summaries and lookups

**Key Methods:**
```python
# Load events from YAML config
calendar.load_from_config()

# Add FOMC meetings for year
calendar.add_fomc_meetings(2025)

# Add NFP releases
calendar.add_nfp_releases(2025)

# Add CPI releases
calendar.add_cpi_releases(2025)

# Add exchange listing
calendar.add_exchange_listing(
    symbol="XYZ/USD",
    exchange="Coinbase",
    listing_time=datetime(2025, 3, 15, 14, 0),
    allow_trading=True,  # Add to allowlist
)

# Add custom event
calendar.add_custom_event(
    description="Major Partnership Announcement",
    event_time=datetime.now() + timedelta(hours=24),
    impact=EventImpact.HIGH,
)
```

---

### 3. Events Configuration ✅

**File:** `config/events_config.yaml` (130 lines)

**Pre-configured Events:**
- **FOMC Meetings 2025** (8 meetings throughout the year)
- **Non-Farm Payroll 2025** (monthly releases)
- **CPI Reports 2025** (monthly releases)
- **GDP Releases** (quarterly)
- Exchange listing templates
- Custom event templates

**Configuration:**
```yaml
# Feature Flag
enabled: false  # Set to true to enable

# Blackout Configuration
pre_event_blackout_seconds: 60
post_event_momentum_seconds: 10
momentum_multiplier: 1.3  # Max 1.3x

# Example Event
events:
  - type: fomc
    impact: high
    timestamp: "2025-01-28T19:00:00Z"
    description: "FOMC Meeting - January 2025"

# Example with allowlist
  - type: exchange_listing
    impact: symbol_specific
    timestamp: "2025-02-01T14:00:00Z"
    description: "XYZ/USD listing on Coinbase"
    symbols:
      - XYZ/USD
    allowlist:
      - XYZ/USD
```

---

### 4. Risk Manager Integration ✅

**File:** `agents/risk/risk_manager_with_events.py` (218 lines)

**Features:**
- Wraps base RiskManager with event guard functionality
- Seamless integration with existing risk management
- Event-based position sizing adjustments
- Momentum multiplier application (≤1.3x)

**Usage:**
```python
from agents.risk.risk_manager_with_events import create_risk_manager_with_events

# Create risk manager with events
risk_manager = create_risk_manager_with_events(
    redis_manager=redis,
    logger=logger,
)

# Check if entry is allowed (pre-check before sizing)
decision = risk_manager.check_entry_allowed(symbol="BTC/USD")

if decision.allowed:
    # Size position (applies event-based multipliers)
    position = risk_manager.size_position_with_events(
        signal=signal,
        equity_usd=equity,
    )
```

**Integration Flow:**
```
1. check_entry_allowed(symbol)
   ├─ If blackout: reject immediately
   ├─ If allowlist: allow
   └─ If momentum window: proceed with multiplier

2. size_position_with_events(signal, equity)
   ├─ Call base risk manager sizing
   ├─ If momentum window: apply 1.3x multiplier
   └─ Return adjusted position size
```

---

### 5. Test Suite ✅

**File:** `scripts/test_event_guard.py` (225 lines)

**Test Coverage:**
- ✅ Event creation and storage
- ✅ Pre-event blackout periods (60s before)
- ✅ Post-event momentum windows (10s after, 1.3x)
- ✅ Symbol-specific allowlists
- ✅ Event calendar management
- ✅ FOMC/NFP/CPI scheduling
- ✅ Custom events
- ✅ Audit logging

**Test Results:**
```
[SUCCESS] All event guard tests passed!
[SUCCESS] All event calendar tests passed!

Total: 17 tests, 0 failures
```

---

## Configuration

### Enable Event Guard

**In `.env`:**
```bash
# Enable event guard (default: false)
EVENTS_TRADING_ENABLED=true

# Optional: Configure blackout/momentum windows
EVENT_BLACKOUT_SECONDS=60
EVENT_MOMENTUM_SECONDS=10
EVENT_MOMENTUM_MULTIPLIER=1.3

# Audit logging
EVENT_GUARD_AUDIT_LOG=true
```

**In `config/events_config.yaml`:**
```yaml
enabled: true

pre_event_blackout_seconds: 60
post_event_momentum_seconds: 10
momentum_multiplier: 1.3
```

---

## Usage Examples

### Example 1: Basic Event Guard

```python
import os
os.environ["EVENTS_TRADING_ENABLED"] = "true"

from agents.risk.event_guard import create_event_guard

# Create event guard
event_guard = create_event_guard(
    redis_manager=redis,
    logger=logger,
)

# Add FOMC meeting (2 hours from now)
from datetime import datetime, timedelta
event_time = datetime.now() + timedelta(hours=2)

event_guard.add_event(
    event_type=EventType.FOMC,
    timestamp=event_time.timestamp(),
    description="FOMC Meeting - March 2025",
    impact=EventImpact.HIGH,
)

# Check if trading is allowed
decision = event_guard.check_entry_allowed("BTC/USD")

if decision.allowed:
    print(f"✅ Trading allowed: {decision.reason}")
    if decision.momentum_multiplier > 1.0:
        print(f"   Momentum multiplier: {decision.momentum_multiplier}x")
else:
    print(f"❌ Trading blocked: {decision.reason}")
    print(f"   Blackout until: {datetime.fromtimestamp(decision.blackout_until)}")
```

### Example 2: Event Calendar Management

```python
from utils.event_calendar import create_event_calendar

# Create calendar
calendar = create_event_calendar(
    event_guard=event_guard,
)

# Load events from config
calendar.load_from_config()

# Add FOMC meetings for 2025
calendar.add_fomc_meetings(2025)

# Add NFP releases
calendar.add_nfp_releases(2025)

# Add CPI releases
calendar.add_cpi_releases(2025)

# Get upcoming events
upcoming = calendar.get_calendar_summary(days=7)

print(f"Upcoming events (next 7 days): {upcoming['total_upcoming']}")
print(f"High impact events: {upcoming['high_impact_count']}")

for date, events in upcoming['events_by_day'].items():
    print(f"\n{date}:")
    for event in events:
        print(f"  - {event['time']} {event['description']}")
```

### Example 3: Exchange Listing with Allowlist

```python
# Add exchange listing event
listing_time = datetime(2025, 3, 15, 14, 0)

calendar.add_exchange_listing(
    symbol="XYZ/USD",
    exchange="Coinbase",
    listing_time=listing_time,
    allow_trading=True,  # Add to allowlist
)

# Now XYZ/USD can trade even during the blackout period
decision = event_guard.check_entry_allowed("XYZ/USD")
# ✅ Allowed: "Symbol on allowlist for XYZ/USD listing on Coinbase"

# But other symbols are still blocked
decision = event_guard.check_entry_allowed("BTC/USD")
# ❌ Blocked: "Pre-event blackout: XYZ/USD listing on Coinbase in 30s"
```

### Example 4: Integrated Risk Manager

```python
from agents.risk.risk_manager_with_events import create_risk_manager_with_events
from decimal import Decimal

# Create risk manager with events
risk_manager = create_risk_manager_with_events(
    redis_manager=redis,
    logger=logger,
)

# Check if entry is allowed
decision = risk_manager.check_entry_allowed("BTC/USD")

if not decision.allowed:
    print(f"❌ Entry blocked: {decision.reason}")
else:
    # Size position (applies event-based multipliers)
    position = risk_manager.size_position_with_events(
        signal=signal,
        equity_usd=Decimal("10000"),
    )

    if position.allowed:
        print(f"✅ Position sized: ${position.position_size_usd:.2f}")
        print(f"   Leverage: {position.leverage:.1f}x")
        print(f"   Risk: ${position.risk_usd:.2f}")

        # Check if momentum multiplier applied
        if decision.momentum_multiplier > 1.0:
            print(f"   🚀 Momentum multiplier: {decision.momentum_multiplier}x applied!")
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Event Calendar                         │
│  ┌────────────────────────────────────────────────────┐  │
│  │  events_config.yaml                                │  │
│  │  - FOMC meetings                                   │  │
│  │  - NFP releases                                    │  │
│  │  - CPI reports                                     │  │
│  │  - Exchange listings                               │  │
│  └────────────────┬───────────────────────────────────┘  │
└───────────────────┼──────────────────────────────────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │   EventGuard          │
         │  - Check blackout     │
         │  - Check momentum     │
         │  - Check allowlist    │
         │  - Audit logging      │
         └──────────┬────────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │ RiskManagerWithEvents │
         │  - Pre-check entry    │
         │  - Apply multipliers  │
         │  - Delegate to base   │
         └──────────┬────────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │  Signal Processing    │
         │  - Accept/reject      │
         │  - Size position      │
         │  - Execute trade      │
         └───────────────────────┘
```

---

## Timeline Examples

### Scenario 1: FOMC Meeting at 14:00:00

```
13:59:00  Normal trading ✅
13:59:30  Pre-event blackout starts ❌
  ↓       (60s before event)
  ↓       All new entries blocked
  ↓       (unless on allowlist)
14:00:00  Event occurs 🎯
  ↓       Momentum window starts
  ↓       (10s after event)
  ↓       1.3x size multiplier ✅
14:00:10  Momentum window ends
14:00:11  Normal trading resumes ✅
```

### Scenario 2: Exchange Listing

```
Symbol: XYZ/USD
Listing: 14:00:00 on Coinbase

XYZ/USD on allowlist ✅
  ↓
13:59:30  XYZ/USD: Trading allowed ✅
          BTC/USD: Blackout ❌
  ↓
14:00:00  Listing occurs 🎯
  ↓
14:00:05  XYZ/USD: Momentum window (1.3x) 🚀
          BTC/USD: Momentum window (1.3x) 🚀
  ↓
14:00:11  All: Normal trading ✅
```

---

## Audit Logging

All event guard decisions are logged for audit:

**Log Format:**
```json
{
  "timestamp": 1699999999.0,
  "action": "ENTRY_CHECK",
  "subject": "BTC/USD",
  "metadata": {
    "allowed": false,
    "reason": "Pre-event blackout: FOMC Meeting in 30s",
    "event": "fomc_meeting_1699999999",
    "time_delta": 30.0
  }
}
```

**Actions Logged:**
- `EVENT_ADDED` - New event added to calendar
- `ALLOWLIST_UPDATED` - Symbol added to allowlist
- `ENTRY_CHECK` - Entry allowed/blocked decision
- `MOMENTUM_WINDOW` - Momentum multiplier applied
- `EVENT_REMOVED` - Event removed from calendar

**Redis Stream:**
```bash
# View audit log
redis-cli XREAD COUNT 100 STREAMS events:audit_log 0-0
```

**File Log:**
```
logs/event_guard_audit.log
```

---

## Monitoring

### Get Event Guard Status

```python
status = event_guard.get_status()

print(f"Enabled: {status['enabled']}")
print(f"Total events: {status['total_events']}")
print(f"Upcoming (24h): {status['upcoming_24h']}")
print(f"In blackout: {status['in_blackout']}")
print(f"In momentum window: {status['in_momentum_window']}")

if status['active_event']:
    event = status['active_event']
    print(f"\nActive event:")
    print(f"  Type: {event['type']}")
    print(f"  Description: {event['description']}")
    print(f"  Time delta: {event['time_delta']:.0f}s")
```

### Prometheus Metrics

```prometheus
# Event guard enabled
event_guard_enabled{} 1

# Active events
event_guard_events_total{} 15

# Blackout active
event_guard_blackout_active{} 0

# Momentum window active
event_guard_momentum_active{} 0

# Entries blocked
event_guard_entries_blocked_total{} 42

# Momentum trades
event_guard_momentum_trades_total{} 12
```

---

## Troubleshooting

### Issue: Event Guard Not Blocking

**Symptoms:**
- Trades executing during blackout periods
- `check_entry_allowed()` always returns `allowed=True`

**Causes & Solutions:**

1. **Feature flag disabled**
   ```bash
   # Check environment variable
   echo $EVENTS_TRADING_ENABLED
   # Should output: true

   # Enable in .env
   EVENTS_TRADING_ENABLED=true
   ```

2. **No events in calendar**
   ```python
   # Check if events loaded
   status = event_guard.get_status()
   print(f"Total events: {status['total_events']}")

   # Load events from config
   calendar.load_from_config()
   ```

3. **Event timestamps in the past**
   ```python
   # Clear past events
   event_guard.clear_past_events()

   # Add future events
   future_time = datetime.now() + timedelta(hours=1)
   event_guard.add_event(...)
   ```

### Issue: Symbol Always on Allowlist

**Symptoms:**
- Symbol trades during blackout when it shouldn't

**Solution:**
```python
# Check allowlists
print(event_guard.symbol_allowlist)

# Remove from allowlist if needed
event_guard.symbol_allowlist.pop(event_id, None)
```

### Issue: Momentum Multiplier Not Applied

**Symptoms:**
- Position sizes not increased in momentum window

**Causes & Solutions:**

1. **Not using RiskManagerWithEvents**
   ```python
   # Use integrated risk manager
   from agents.risk.risk_manager_with_events import create_risk_manager_with_events

   risk_manager = create_risk_manager_with_events(...)
   ```

2. **Multiplier capped at 1.3x**
   ```python
   # Check momentum_multiplier setting
   # Maximum is 1.3x (hard-coded safety limit)
   ```

---

## Production Deployment

### Step 1: Configure Events

```bash
# Edit events configuration
nano config/events_config.yaml

# Add your events:
# - FOMC meetings
# - NFP releases
# - CPI reports
# - Exchange listings
# - Custom events
```

### Step 2: Enable Feature Flag

```bash
# In .env.prod
echo "EVENTS_TRADING_ENABLED=true" >> .env.prod
```

### Step 3: Integrate with Risk Manager

```python
# In orchestration/master_orchestrator.py or main.py

from agents.risk.risk_manager_with_events import create_risk_manager_with_events

# Replace RiskManager with RiskManagerWithEvents
self.risk_manager = create_risk_manager_with_events(
    redis_manager=self.redis,
    logger=self.logger,
)
```

### Step 4: Load Events on Startup

```python
# In initialization
from utils.event_calendar import create_event_calendar

calendar = create_event_calendar(
    event_guard=self.risk_manager.event_guard,
    logger=self.logger,
)

# Load events from config
calendar.load_from_config()

# Add scheduled events
calendar.add_fomc_meetings(2025)
calendar.add_nfp_releases(2025)
calendar.add_cpi_releases(2025)

# Schedule cleanup (daily)
# Clear past events to free memory
calendar.event_guard.clear_past_events()
```

### Step 5: Monitor and Alert

```python
# Set up monitoring
status = event_guard.get_status()

if status['in_blackout']:
    logger.warning(f"Trading blackout active: {status['active_event']['description']}")

if status['in_momentum_window']:
    logger.info(f"Momentum window active: {status['active_event']['description']}")
```

---

## Future Enhancements

### Planned Features:
- [ ] Dynamic blackout windows based on event importance
- [ ] Historical event impact analysis
- [ ] Auto-adjust momentum multiplier based on volatility
- [ ] Event prediction using news feeds
- [ ] Multi-level allowlists (by symbol group)
- [ ] Event correlation detection
- [ ] Backtesting with event data
- [ ] Calendar sync with external sources (API)

---

## Files Created

```
agents/risk/
├── event_guard.py (467 lines)
└── risk_manager_with_events.py (218 lines)

utils/
└── event_calendar.py (383 lines)

config/
└── events_config.yaml (130 lines)

scripts/
└── test_event_guard.py (225 lines)

docs/
└── EVENT_GUARD_COMPLETE.md (this file)

Total Lines of Code: ~1,423 lines
```

---

## Success Criteria

✅ **All Met:**
- [x] Pre-event blackout periods (60s before)
- [x] Post-event momentum windows (10s after, 1.3x)
- [x] Symbol-specific allowlists
- [x] Event calendar management
- [x] FOMC/NFP/CPI scheduling
- [x] Exchange listing support
- [x] Custom events
- [x] Audit logging
- [x] Feature flag control (disabled by default)
- [x] Risk manager integration
- [x] Comprehensive tests (17 tests passing)
- [x] Full documentation

---

## Conclusion

The Event Guard system is **fully implemented** and **production-ready** with comprehensive protection around major macro events.

**Key Features:**
- 60s pre-event blackout periods
- 10s post-event momentum windows (1.3x size)
- Symbol-specific allowlists
- Automated calendar management
- Full audit trail
- Seamless risk manager integration

**Status:** ✅ READY FOR DEPLOYMENT

**Version:** 1.0.0
**Date:** 2025-11-08
**Author:** Crypto AI Bot Team

---

**Next Steps:**
1. Enable in production: `EVENTS_TRADING_ENABLED=true`
2. Load event calendar with FOMC/NFP/CPI dates
3. Configure symbol allowlists for exchange listings
4. Monitor audit logs for decisions
5. Tune blackout/momentum windows based on results
