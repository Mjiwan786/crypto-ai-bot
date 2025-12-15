# A1 - Configuration Audit Report
## crypto-ai-bot Publisher & Stream Configuration

**Date**: 2025-11-08
**Purpose**: Audit current configuration hooks for pair and stream management

---

## Executive Summary

Current system uses **environment variables** for pair and stream configuration. No code changes required - hooks already exist.

**Existing Hooks**:
- ✅ `TRADING_PAIRS` - CSV list of trading pairs
- ✅ `STREAM_SIGNALS_PAPER` - Redis stream name override
- ✅ `REDIS_URL` - Redis connection URL

**Finding**: Can implement staging with zero code changes using existing env var infrastructure.

---

## 1. Pair Configuration

### Current Implementation

**File**: `agents/core/signal_processor.py`
**Line**: 513-515

```python
"trading_pairs": os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD,SOL/USD,ADA/USD").split(","),
```

### Environment Variable

| Env Var | Type | Default | Format |
|---------|------|---------|--------|
| `TRADING_PAIRS` | CSV string | `BTC/USD,ETH/USD,SOL/USD,ADA/USD` | Comma-separated pairs with slash delimiter |

### Usage Example

```bash
# Current production
TRADING_PAIRS="BTC/USD,ETH/USD"

# Staging with new pairs
TRADING_PAIRS="BTC/USD,ETH/USD,SOL/USD,ADA/USD,AVAX/USD"
```

**Note**: System already supports slash format (`BTC/USD`), not hyphen format (`BTC-USD`).

---

## 2. Redis Stream Configuration

### Current Implementation

**File**: `agents/core/signal_processor.py`
**Lines**: 399, 488

#### Router Default Stream (Line 399)
```python
"default": os.getenv("STREAM_SIGNALS_PAPER", "signals:paper"),
```

#### Processed Signals Stream (Line 488)
```python
"processed_signals": os.getenv("STREAM_SIGNALS_PAPER", "signals:paper"),
```

### Environment Variable

| Env Var | Type | Default | Purpose |
|---------|------|---------|---------|
| `STREAM_SIGNALS_PAPER` | String | `signals:paper` | Redis stream key for processed signals |

### Usage Example

```bash
# Current production
STREAM_SIGNALS_PAPER="signals:paper"

# Staging stream
STREAM_SIGNALS_PAPER="signals:paper:staging"

# Live trading
STREAM_SIGNALS_PAPER="signals:live"
```

---

## 3. Additional Configuration Hooks

### Redis Connection

**Environment Variable**: `REDIS_URL`

```bash
# Redis Cloud with TLS
REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
```

**TLS Certificate**:
- Path: `config/certs/redis_ca.pem`
- Loaded automatically if `rediss://` protocol detected

### Stream Retention (XTRIM)

**File**: `agents/core/signal_processor.py`
**Lines**: 96-99

```python
self.maxlen_signals = int(os.getenv('STREAM_MAXLEN_SIGNALS', '10000'))
self.maxlen_pnl = int(os.getenv('STREAM_MAXLEN_PNL', '5000'))
self.maxlen_heartbeat = int(os.getenv('STREAM_MAXLEN_HEARTBEAT', '1000'))
self.maxlen_metrics = int(os.getenv('STREAM_MAXLEN_METRICS', '10000'))
```

---

## 4. Configuration Loading Flow

### Entry Point

**File**: `main.py`
**Flow**:
1. CLI args parsed (`--mode`, `--config`, `--strategy`)
2. Loads `config/settings.yaml` via `unified_config_loader`
3. Creates `MasterOrchestrator` instance
4. Orchestrator initializes `SignalProcessor`
5. `SignalProcessor` reads env vars in `_load_config()` method

### Environment Loading

**File**: `agents/core/signal_processor.py`
**Line**: 44

```python
def _load_env():
    """Load environment variables - call this explicitly in __init__ or startup."""
    load_dotenv()
```

**Called at**: Line 444 in `__init__` method

---

## 5. Proposed Minimal Changes (Optional)

### Option A: Use Existing Hooks (RECOMMENDED)

**No code changes required**. Create `.env.staging` file:

```bash
# .env.staging
REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
REDIS_SSL=true
REDIS_SSL_CA_CERT="config/certs/redis_ca.pem"

# Stream configuration
STREAM_SIGNALS_PAPER="signals:paper:staging"

# Pair configuration
TRADING_PAIRS="BTC/USD,ETH/USD,SOL/USD,ADA/USD,AVAX/USD"

# Mode flag (for clarity)
TRADING_MODE="paper"
STAGING_MODE="true"
```

**Usage**:
```bash
# Load staging env and run
python -m dotenv -f .env.staging run main.py run --mode paper

# Or explicitly load in startup script
```

### Option B: Add Wrapper Variables (User Requested)

If you want the specific naming from your prompt:

1. **Add REDIS_STREAM_NAME** (alias for STREAM_SIGNALS_PAPER)
2. **Add EXTRA_PAIRS** (merged with TRADING_PAIRS)
3. **Add PUBLISH_MODE** (maps to stream names)

**File to modify**: `agents/core/signal_processor.py` method `_load_config()`

**Proposed changes** (around line 488):

```python
# Backward compatible stream selection
publish_mode = os.getenv("PUBLISH_MODE", "paper")  # paper|staging|live
redis_stream_name = os.getenv("REDIS_STREAM_NAME")  # Optional override

if redis_stream_name:
    # Direct override
    processed_signals_stream = redis_stream_name
elif publish_mode == "staging":
    processed_signals_stream = "signals:paper:staging"
elif publish_mode == "live":
    processed_signals_stream = "signals:live"
else:
    # Default to STREAM_SIGNALS_PAPER or fallback
    processed_signals_stream = os.getenv("STREAM_SIGNALS_PAPER", "signals:paper")

config["redis_streams"]["processed_signals"] = processed_signals_stream
```

**Proposed changes** (around line 513):

```python
# Base pairs
base_pairs = os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD").split(",")

# Extra pairs (additive)
extra_pairs_str = os.getenv("EXTRA_PAIRS", "")
extra_pairs = [p.strip() for p in extra_pairs_str.split(",") if p.strip()]

# Merge and deduplicate
all_pairs = list(dict.fromkeys(base_pairs + extra_pairs))

config["trading_pairs"] = all_pairs
```

---

## 6. Symbol Format Handling

### Current Format: Slash Delimiter

**Throughout codebase**: `BTC/USD`, `ETH/USD`, `SOL/USD`

**Evidence**:
- `agents/core/signal_processor.py:513`: `"BTC/USD,ETH/USD,SOL/USD,ADA/USD"`
- `.env.staging`: `TRADING_PAIRS=BTC/USD,ETH/USD,SOL/USD,ADA/USD,AVAX/USD`

### If Hyphen Format Required

**Option 1**: Normalize on input (recommended)

```python
# In _load_config()
pairs_raw = os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD").split(",")
pairs_normalized = [p.strip().replace("/", "-") for p in pairs_raw]
config["trading_pairs"] = pairs_normalized
```

**Option 2**: Accept both formats

```python
def normalize_pair_symbol(pair: str) -> str:
    """Normalize pair symbol to internal format"""
    return pair.strip().replace("-", "/")  # Or "/" to "-"

pairs_raw = os.getenv("TRADING_PAIRS", "").split(",")
config["trading_pairs"] = [normalize_pair_symbol(p) for p in pairs_raw if p.strip()]
```

**Recommendation**: Keep slash format (current standard in codebase).

---

## 7. File Paths Summary

### Configuration Files
- `agents/core/signal_processor.py` - Main signal processor logic
- `main.py` - Entry point and orchestration
- `config/settings.yaml` - Base configuration (YAML)
- `config/unified_config_loader.py` - Config loading logic

### Environment Files
- `.env` - Production environment
- `.env.staging` - Staging environment (already created)
- `.env.example` - Template with defaults

### Certificates
- `config/certs/redis_ca.pem` - Redis Cloud TLS certificate

---

## 8. Exact Hooks Available (Zero Changes Needed)

### For Stream Override

```bash
STREAM_SIGNALS_PAPER="signals:paper:staging"
```

**Where used**:
- `agents/core/signal_processor.py:399` (router default)
- `agents/core/signal_processor.py:488` (processed signals)

### For Pair Configuration

```bash
TRADING_PAIRS="BTC/USD,ETH/USD,SOL/USD,ADA/USD,AVAX/USD"
```

**Where used**:
- `agents/core/signal_processor.py:513` (trading pairs list)

### For Redis Connection

```bash
REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
REDIS_SSL_CA_CERT="config/certs/redis_ca.pem"
```

**Where used**:
- `agents/core/signal_processor.py:484` (redis_url)
- TLS certificate loaded automatically for `rediss://` URLs

---

## 9. Proposed Minimal Implementation

### Option 1: Zero Code Changes (RECOMMENDED)

**Use existing hooks + .env.staging file**

✅ Already implemented in previous work:
- `.env.staging` created with correct variables
- `run_staging_publisher.py` startup script
- Stream isolation tested and validated

**Ready to use**:
```bash
conda activate crypto-bot
python run_staging_publisher.py
```

### Option 2: Add User-Requested Aliases

**Add these helper variables** (backward compatible):

1. `PUBLISH_MODE` → maps to stream selection
2. `REDIS_STREAM_NAME` → direct stream override
3. `EXTRA_PAIRS` → additive to TRADING_PAIRS

**Implementation**: ~20 lines in `signal_processor.py:_load_config()`

**Benefit**: More explicit naming, clearer intent

**Tradeoff**: Adds slight complexity, but maintains backward compatibility

---

## 10. Recommendation

**Use Option 1** (existing hooks with .env.staging):

**Reasons**:
1. Zero code changes required
2. Already tested and validated
3. Maintains simplicity
4. Fully backward compatible
5. `.env.staging` already created and ready

**Next step**: Proceed to A2 only if you want the explicit PUBLISH_MODE/EXTRA_PAIRS/REDIS_STREAM_NAME wrapper layer.

---

## Appendix: Environment Variables Reference

| Variable | Purpose | Default | Used In |
|----------|---------|---------|---------|
| `REDIS_URL` | Redis connection | - | signal_processor.py:484 |
| `REDIS_SSL_CA_CERT` | TLS cert path | - | Auto-loaded for rediss:// |
| `STREAM_SIGNALS_PAPER` | Stream name | `signals:paper` | signal_processor.py:399,488 |
| `TRADING_PAIRS` | Pair list (CSV) | `BTC/USD,ETH/USD,SOL/USD,ADA/USD` | signal_processor.py:513 |
| `STREAM_MAXLEN_SIGNALS` | XTRIM limit | `10000` | signal_processor.py:96 |
| `MIN_CONFIDENCE` | Signal filter | `0.7` | signal_processor.py:493 |
| `LOG_LEVEL` | Logging level | `INFO` | main.py:472 |

---

**Status**: Audit complete ✅
**Recommendation**: Use existing hooks (Option 1) - zero code changes required
**Next Phase**: A2 (Optional wrapper layer) or skip to A3 (Run staging publisher)
