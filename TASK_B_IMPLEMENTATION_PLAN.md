# Task B Implementation Plan - Kraken WebSockets, OHLCV, and Multi-Pair Support

**Date:** 2025-01-27  
**Status:** In Progress

---

## Current State Analysis

### ✅ What's Working

1. **Kraken WebSocket Client** (`utils/kraken_ws.py`)
   - Connection management with state tracking
   - Reconnection logic with exponential backoff (mostly correct)
   - Subscription setup for ticker, trade, spread, book, OHLC
   - Message handling and validation
   - Circuit breakers

2. **OHLCV Manager** (`utils/kraken_ohlcv_manager.py`)
   - Loads configuration from `kraken_ohlcv.yaml`
   - Handles native OHLCV subscriptions
   - Generates synthetic bars from trades
   - Publishes to Redis streams

3. **Synthetic Bar Builder** (`utils/synthetic_bars.py`, `utils/kraken_ohlcv_manager.py`)
   - Time-bucketing for sub-minute bars
   - Quality filtering (min trades per bucket)

### ⚠️ Issues Found

1. **Pairs Not Loaded from Config**
   - `KrakenWSConfig` loads pairs from `TRADING_PAIRS` env var (default: "BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD")
   - Missing: BTC/EUR, ADA/USD, AVAX/USD
   - Should load from `kraken_ohlcv.yaml` instead

2. **Timeframes Not Loaded from Config**
   - `KrakenWSConfig` loads timeframes from `TIMEFRAMES` env var (default: "15s,1m,3m,5m")
   - Missing: 15m, 30m, 1h, 4h, 1d (native) and 30s (synthetic)
   - Should load from `kraken_ohlcv.yaml` instead

3. **OHLC Subscription Logic**
   - Line 1198-1213: Only handles hardcoded timeframes
   - Doesn't use config loader
   - Missing some native timeframes (e.g., 30m, 4h, 1d)

4. **Reconnection Backoff**
   - ✅ Uses exponential backoff (doubles each time)
   - ✅ Caps at 60s
   - ✅ Max 10 attempts
   - ⚠️ Starts at `reconnect_delay` (default 1s) - correct
   - ⚠️ But backoff is reset to `reconnect_delay` on success, which is correct

5. **Health Metrics**
   - ❌ Missing: last message timestamp per pair
   - ❌ Missing: reconnect count per pair
   - ✅ Has: overall reconnect count, overall stats

6. **Subscription Error Logging**
   - ✅ Has error logging at line 1226
   - ⚠️ Could be more detailed (which pair, which channel failed)

7. **Stream Naming**
   - ⚠️ OHLCV manager uses `kraken:ohlc:{tf}:{pair}` (correct)
   - ⚠️ But pair format might not match config exactly

---

## Implementation Plan

### Step 1: Create Configuration Loader ✅

**File:** `utils/kraken_config_loader.py` (CREATED)

**Features:**
- Loads pairs from `kraken_ohlcv.yaml` (tier_1, tier_2, tier_3)
- Loads timeframes from `kraken_ohlcv.yaml` (primary, synthetic)
- Handles feature flags (e.g., ENABLE_5S_BARS)
- Provides Kraken pair format conversion
- Validates configuration

---

### Step 2: Update KrakenWSConfig to Use Config Loader

**File:** `utils/kraken_ws.py`

**Changes:**
1. Import `get_kraken_config_loader`
2. Update `KrakenWSConfig.pairs` to load from config loader
3. Update `KrakenWSConfig.timeframes` to load from config loader
4. Add fallback to env vars if config not found

---

### Step 3: Fix OHLC Subscription Logic

**File:** `utils/kraken_ws.py` (line 1197-1213)

**Changes:**
1. Use config loader to get native timeframes
2. Subscribe to all native timeframes from config
3. Remove hardcoded timeframe list
4. Use `get_kraken_ohlc_intervals()` from config loader

---

### Step 4: Fix Reconnection Backoff

**File:** `utils/kraken_ws.py` (line 2379-2476)

**Changes:**
1. ✅ Already uses exponential backoff (1s, 2s, 4s...)
2. ✅ Already caps at 60s
3. ✅ Already max 10 attempts
4. ⚠️ Verify backoff starts at 1s (default reconnect_delay=1)
5. Add comment documenting PRD-001 compliance

---

### Step 5: Add Health Metrics

**File:** `utils/kraken_ws.py`

**Changes:**
1. Add `last_message_timestamp_by_pair: Dict[str, float]` to stats
2. Add `reconnect_count_by_pair: Dict[str, int]` to stats
3. Update `handle_trade_data`, `handle_ohlc_data`, etc. to track last message timestamp
4. Update reconnection logic to track reconnect count per pair
5. Add method `get_health_metrics()` that returns:
   - Last message timestamp per pair
   - Reconnect count per pair
   - Overall connection health

---

### Step 6: Enhance Subscription Error Logging

**File:** `utils/kraken_ws.py` (line 1215-1230)

**Changes:**
1. Log which pair failed (if subscription is pair-specific)
2. Log which channel failed (ticker, trade, ohlc, etc.)
3. Log subscription payload for debugging
4. Track subscription errors per pair/channel

---

### Step 7: Verify Stream Naming

**File:** `utils/kraken_ohlcv_manager.py`

**Changes:**
1. Verify stream naming matches `kraken_ohlcv.yaml` exactly
2. Use config loader's `get_stream_name()` method
3. Ensure pair format is consistent (BTC/USD -> BTC-USD)

---

### Step 8: Add Integration Tests

**File:** `tests/integration/test_kraken_ws_ohlcv.py` (NEW)

**Tests:**
1. Test configuration loader loads all pairs from kraken_ohlcv.yaml
2. Test configuration loader loads all timeframes from kraken_ohlcv.yaml
3. Test WebSocket client subscribes to all pairs
4. Test WebSocket client subscribes to all native timeframes
5. Test synthetic bar generation for all synthetic timeframes
6. Test stream naming matches config
7. Test reconnection logic (mocked)
8. Test health metrics collection

---

## Files to Create/Modify

### New Files
1. ✅ `utils/kraken_config_loader.py` - Configuration loader (CREATED)
2. `tests/integration/test_kraken_ws_ohlcv.py` - Integration tests

### Modified Files
1. `utils/kraken_ws.py` - Update to use config loader, fix subscriptions, add health metrics
2. `utils/kraken_ohlcv_manager.py` - Verify stream naming, use config loader

---

## Verification Checklist

- [ ] All pairs from kraken_ohlcv.yaml are subscribed (BTC/USD, ETH/USD, BTC/EUR, ADA/USD, SOL/USD, AVAX/USD, LINK/USD)
- [ ] All native timeframes are subscribed (1m, 5m, 15m, 30m, 1h, 4h, 1d)
- [ ] All synthetic timeframes are generated (5s if enabled, 15s, 30s)
- [ ] Reconnection uses exponential backoff (1s, 2s, 4s... max 60s)
- [ ] Max 10 reconnection attempts
- [ ] Health metrics track last message timestamp per pair
- [ ] Health metrics track reconnect count per pair
- [ ] Subscription errors are logged with context (pair, channel)
- [ ] Stream naming matches kraken_ohlcv.yaml (kraken:ohlc:<tf>:<pair>)
- [ ] Integration tests verify all pairs/timeframes are active

---

## Next Steps

1. Update `KrakenWSConfig` to use config loader
2. Fix OHLC subscription logic
3. Add health metrics
4. Enhance error logging
5. Add integration tests









