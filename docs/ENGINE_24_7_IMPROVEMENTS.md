# Engine 24/7 Operation Improvements
## Long-Running Stability, Reconnect Logic, and Shutdown Paths

**Date:** 2025-01-XX  
**Status:** ✅ Complete  
**Files Modified:** `main_engine.py`, `utils/kraken_ws.py`

---

## Overview

This document describes improvements made to ensure the engine can run reliably 24/7 in production, with robust reconnection logic, graceful shutdown, and clear separation between paper and live trading modes.

---

## Main Entrypoints

### Production Entrypoints

1. **`main_engine.py`** (Primary)
   - Single canonical entrypoint for production
   - Usage: `python main_engine.py --mode paper|live`
   - Features: Task supervision, health publishing, graceful shutdown

2. **`production_engine.py`** (Alternative)
   - Alternative production entrypoint
   - Usage: `python production_engine.py --mode paper|live`
   - Features: Integrated health endpoint, PnL tracking

### Entrypoint Selection

The engine uses `main_engine.py` as the primary entrypoint. Both entrypoints support:
- `--mode paper`: Paper trading mode (default)
- `--mode live`: Live trading mode (requires confirmation)

---

## Improvements Made

### 1. ✅ Graceful Shutdown and Restart

**Location:** `main_engine.py::MainEngine.shutdown()`

**Changes:**
- Added 30-second timeout per PRD-001 Section 9.1
- Sequential shutdown with timeouts:
  - Task supervisor: 25s timeout
  - Health publisher: 3s timeout
  - Redis client: 2s timeout
- Logs shutdown duration and runtime before shutdown
- Handles timeout errors gracefully (logs warning, continues cleanup)

**Key Features:**
- Shutdown completes within 30s (Fly.io requirement)
- Logs runtime duration for uptime correlation
- Handles partial shutdown failures gracefully

**Code:**
```python
async def shutdown(self):
    """
    Graceful shutdown with timeout (PRD-001 Section 9.1).
    
    For 24/7 operation, shutdown must:
    1. Stop accepting new work (signal generation)
    2. Flush pending Redis publishes
    3. Close WebSocket connections cleanly
    4. Complete within 30 seconds (Fly.io requirement)
    """
    # ... implementation with timeouts
```

---

### 2. ✅ Enhanced Reconnect Logging

**Location:** `utils/kraken_ws.py::KrakenWebSocketClient.start()`

**Changes:**
- Added structured logging with context fields:
  - `component`: "kraken_ws"
  - `reconnection_attempt`: Current attempt number
  - `max_retries`: Maximum retries allowed
  - `downtime_seconds`: Time spent disconnected
  - `connection_state`: Current connection state
  - `error_type`: Type of error (for debugging)
  - `pairs`: Trading pairs affected
- Enhanced error logging:
  - Truncates long error messages (200 chars)
  - Logs error type separately from message
  - Full traceback only in DEBUG mode
- Success logging:
  - Logs previous attempt count on successful reconnect
  - Includes pairs affected

**Key Features:**
- Structured logs for log aggregation systems
- Context fields enable filtering and correlation
- Error details without overwhelming logs
- Clear indication of reconnect success/failure

**Example Log Output:**
```
WARNING: Kraken WS reconnect triggered: attempt=3/10, downtime=12.5s, 
         state=RECONNECTING, error_type=ConnectionClosed, error=...
INFO: Reconnection attempt 3/10: waiting 4.2s before retry 
      (base=4.0s, jitter=+5%, pairs=['BTC/USD', 'ETH/USD'])
INFO: Connection successful - reconnection attempt counter reset to 0 
      (previous attempts=3, pairs=['BTC/USD', 'ETH/USD'])
```

---

### 3. ✅ Clear Separation of Paper vs Live Trading Paths

**Location:** `main_engine.py::EngineSettings`

**Changes:**
- Standardized on `ENGINE_MODE` (PRD-001 compliant)
  - `ENGINE_MODE` is authoritative
  - `TRADING_MODE` is legacy fallback (backward compatibility)
- Mode validation at startup:
  - Fails fast if mode is invalid
  - Logs warning for live mode (real money at risk)
- Stream routing based on mode:
  - `signals:paper:<PAIR>` for paper mode
  - `signals:live:<PAIR>` for live mode
- Clear logging of mode and stream routing

**Key Features:**
- Mode cannot be changed without restart
- Strict separation enforced at stream level
- Clear logging helps operators verify mode
- Validation prevents accidental mode mixing

**Code:**
```python
@dataclass
class EngineSettings:
    """
    MODE SEPARATION (PRD-001):
    - ENGINE_MODE determines stream routing: "paper" → signals:paper:<PAIR>, "live" → signals:live:<PAIR>
    - Paper and live modes are strictly separated - never mix data
    - Mode is set at startup and cannot be changed without restart
    """
    engine_mode: str = field(default_factory=lambda: os.getenv("ENGINE_MODE") or os.getenv("TRADING_MODE", "paper"))
```

---

### 4. ✅ Enhanced Comments for 24/7 Maintenance

**Added Comments:**

1. **Main Engine Loop** (`main_engine.py::MainEngine.run()`)
   - Explains long-running loop behavior
   - Documents shutdown triggers
   - Describes 24/7 operation requirements

2. **Signal Generation Loop** (`main_engine.py::create_signal_generator()`)
   - Explains mode separation
   - Documents stream routing
   - Describes reconnection behavior

3. **Task Supervisor** (`main_engine.py::TaskSupervisor`)
   - Explains automatic restart behavior
   - Documents exponential backoff
   - Describes restart limits

4. **Reconnection Logic** (`utils/kraken_ws.py::start()`)
   - Explains reconnect attempts and backoff
   - Documents max retries behavior
   - Describes health implications

5. **Shutdown Path** (`main_engine.py::MainEngine.shutdown()`)
   - Explains timeout requirements
   - Documents cleanup sequence
   - Describes Fly.io integration

---

## Long-Running Loop Behavior

### Main Loop (`main_engine.py::MainEngine.run()`)

**Flow:**
1. Setup signal handlers (SIGTERM/SIGINT)
2. Initialize components (Redis, health publisher, tasks)
3. Start supervised tasks (signal generation with auto-restart)
4. Wait for shutdown signal (blocks indefinitely)
5. Perform graceful shutdown (30s timeout)

**Shutdown Triggers:**
- SIGTERM: Fly.io restart, deployment, manual stop
- SIGINT: Ctrl+C (development/testing)
- Critical error: Max reconnection attempts exceeded

**24/7 Requirements:**
- Handles network interruptions (reconnection logic)
- Handles Redis failures (retry logic)
- Handles task failures (automatic restart)
- Maintains health status (heartbeat publishing)

---

## Reconnection Logic

### WebSocket Reconnection (`utils/kraken_ws.py::start()`)

**Behavior:**
- Exponential backoff: 1s → 2s → 4s → ... → max 60s
- ±20% jitter to prevent thundering herd
- Max 10 retries before marking unhealthy
- Automatic resubscription on reconnect

**Logging:**
- Structured logs with context fields
- Error type and message logged separately
- Full traceback only in DEBUG mode
- Success logged with previous attempt count

**Health Implications:**
- Healthy: Connected and receiving data
- Unhealthy: Max retries exceeded (requires intervention)
- Reconnecting: Transient failure (automatic recovery)

---

## Mode Separation

### Paper vs Live Mode

**Paper Mode:**
- Streams: `signals:paper:<PAIR>`, `pnl:paper:equity_curve`
- No real money at risk
- No API keys required
- Relaxed validation

**Live Mode:**
- Streams: `signals:live:<PAIR>`, `pnl:live:equity_curve`
- Real money at risk
- Requires `LIVE_TRADING_CONFIRMATION`
- Strict validation

**Enforcement:**
- Mode validated at startup (fails fast if invalid)
- Stream routing based on mode (cannot mix)
- Mode logged clearly at startup
- Warning logged for live mode

---

## Testing Recommendations

### Graceful Shutdown Testing

```bash
# Test graceful shutdown
python main_engine.py --mode paper &
PID=$!
sleep 10
kill -TERM $PID
# Verify shutdown completes within 30s
```

### Reconnection Testing

```bash
# Test reconnection logic
# Simulate network interruption
# Verify exponential backoff and logging
```

### Mode Separation Testing

```bash
# Test paper mode
python main_engine.py --mode paper
# Verify streams: signals:paper:<PAIR>

# Test live mode
python main_engine.py --mode live
# Verify streams: signals:live:<PAIR>
```

---

## Monitoring

### Key Metrics

- **Reconnection attempts**: `kraken_ws_reconnects_total` (Prometheus)
- **Connection state**: `connection_state` (Redis)
- **Uptime**: `uptime_seconds` (health endpoint)
- **Mode**: `mode` (health endpoint, logs)

### Key Logs

- **Reconnection**: `"Kraken WS reconnect triggered"`
- **Success**: `"Connection successful - reconnection attempt counter reset"`
- **Failure**: `"Kraken WS max reconnection attempts reached"`
- **Shutdown**: `"Engine shutdown complete"`

---

## Files Modified

### `main_engine.py`
- Enhanced `EngineSettings` with mode separation comments
- Added mode validation in `initialize()`
- Enhanced `shutdown()` with timeout handling
- Added comments to `run()` explaining 24/7 operation
- Enhanced `_request_shutdown()` with logging
- Updated `signal_generation_loop()` with mode separation comments
- Updated stream properties to use `engine_mode`

### `utils/kraken_ws.py`
- Enhanced reconnect logging with structured fields
- Added error type and message separation
- Enhanced success logging with previous attempt count
- Added comments explaining 24/7 reconnection behavior

---

## Conclusion

The engine is now optimized for 24/7 operation with:
- ✅ Robust graceful shutdown (30s timeout)
- ✅ Enhanced reconnect logging (structured, contextual)
- ✅ Clear mode separation (paper vs live)
- ✅ Comprehensive comments for maintenance

All improvements are backward compatible and follow PRD-001 requirements.

---

**Document Status:** Complete  
**Next Review:** After production deployment  
**Owner:** Engineering Team

