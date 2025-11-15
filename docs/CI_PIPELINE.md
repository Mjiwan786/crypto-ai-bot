# CI Pipeline - Crypto AI Bot

**Automated testing and validation using canonical scripts only.**

## Overview

The CI pipeline uses **7 jobs** that run on every push and pull request to `main`, `master`, and `develop` branches. All jobs use the **canonical scripts** from the `scripts/` directory, ensuring consistency between local development and CI environments.

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────┐
│  FAST CHECKS (Parallel)                                 │
├─────────────────────────────────────────────────────────┤
│  1. Preflight Checks (scripts/preflight.py)             │
│  2. MCP Smoke Test (scripts/mcp_smoke.py) - hermetic    │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│  MAIN TESTS (Parallel)                                  │
├─────────────────────────────────────────────────────────┤
│  3. Tests & Linting (pytest, ruff, mypy)                │
│  4. Redis Smoke (scripts/redis_cloud_smoke.py) *        │
└──────────────────┬──────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────┐
│  EXTENDED CHECKS (Sequential)                           │
├─────────────────────────────────────────────────────────┤
│  5. Backtest Smoke (scripts/backtest.py smoke)          │
│  6. Security Checks (safety, bandit)                    │
│  7. Build Package                                       │
└─────────────────────────────────────────────────────────┘

* Redis Smoke only runs if REDIS_URL secret is set
```

## Jobs

### 1. Preflight Checks (preflight)

**Purpose:** Validate environment and configuration before running tests.

**Command:**
```bash
python scripts/preflight.py --mode dev --strict
```

**Checks:**
- Python 3.10.18 version
- Environment templates present
- No real .env files
- Required ports free
- File permissions

**Exit Codes:**
- `0` = READY (all checks passed)
- `1` = NOT_READY (critical failures)
- `2` = DEGRADED (warnings in non-strict mode)

**Duration:** ~5-10 seconds

---

### 2. MCP Schema Smoke Test (mcp-smoke)

**Purpose:** Validate MCP schemas and JSON marshaling (hermetic - no network).

**Command:**
```bash
python scripts/mcp_smoke.py --verbose
```

**Tests:**
- SignalModel validation and serialization
- MCP Signal schema
- OrderIntent schema
- Fill schema
- ContextSnapshot schema
- Metric schema
- MarketSnapshot schema
- RegimeLabel enum

**Hermetic:** No network traffic, no Redis required.

**Duration:** ~5-10 seconds

---

### 3. Tests & Linting (test)

**Purpose:** Run full test suite with linting and type checking.

**Commands:**
```bash
ruff check .                           # Linting
mypy . --ignore-missing-imports        # Type checking
pytest -q --cov=. --cov-report=xml     # Unit tests with coverage
```

**Runs After:** preflight, mcp-smoke (both must pass)

**Output:**
- Test results
- Coverage report (uploaded to Codecov)
- Linting violations
- Type errors

**Continue on Error:** Linting and type checking are non-blocking

**Duration:** ~30-60 seconds

---

### 4. Redis Cloud Smoke Test (redis-smoke)

**Purpose:** Test Redis Cloud TLS connection (conditional on secret).

**Command:**
```bash
python scripts/redis_cloud_smoke.py --duration 0
```

**Conditional:** Only runs if `REDIS_URL` secret is set.

**Tests:**
- Basic Redis connection with TLS
- Health check with latency measurement
- Stream operations (xadd/xread)
- TLS verification

**Duration:** ~10-15 seconds

**Environment:**
```yaml
env:
  REDIS_URL: ${{ secrets.REDIS_URL }}
```

**Setup Secret:**
```bash
# GitHub repo settings → Secrets → Actions → New repository secret
Name: REDIS_URL
Value: redis://default:<password>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
```

---

### 5. Backtest Smoke Test (backtest-smoke)

**Purpose:** Validate all trading strategies can initialize.

**Command:**
```bash
python scripts/backtest.py smoke --quick
```

**Tests:**
- Breakout strategy initialization
- Momentum strategy initialization
- Mean reversion strategy initialization
- Regime router initialization

**Runs After:** test (must pass)

**Duration:** ~15-30 seconds

---

### 6. Security Checks (security)

**Purpose:** Scan for security vulnerabilities and code issues.

**Commands:**
```bash
pip freeze | safety check --stdin          # Dependency vulnerabilities
bandit -r . -f json -o bandit-report.json  # Code security issues
```

**Output:**
- Safety report (dependency vulnerabilities)
- Bandit report (uploaded as artifact)

**Continue on Error:** Security checks are non-blocking

**Duration:** ~20-30 seconds

---

### 7. Build Package (build)

**Purpose:** Build Python package and verify artifacts.

**Commands:**
```bash
python -m build                    # Build wheel and sdist
python -m twine check dist/*       # Verify package metadata
```

**Runs After:** test, security (both must pass)

**Output:**
- Package wheel (.whl)
- Source distribution (.tar.gz)
- Build artifacts (uploaded)

**Duration:** ~10-20 seconds

---

## Total Pipeline Duration

**Fast path (no Redis):** ~1-2 minutes
**Full path (with Redis):** ~2-3 minutes

### Job Dependencies

```
preflight ──┐
            ├─→ test ──┐
mcp-smoke ──┤          ├─→ backtest-smoke
            │          │
            └─→ redis-smoke
                       │
                       ├─→ security ──┐
                       │              ├─→ build
                       └──────────────┘
```

---

## Canonical Scripts Used

All CI jobs use canonical scripts from `scripts/`:

| Script | Job | Purpose |
|--------|-----|---------|
| `preflight.py` | preflight | Environment validation |
| `mcp_smoke.py` | mcp-smoke | Schema testing (hermetic) |
| `redis_cloud_smoke.py` | redis-smoke | Redis Cloud TLS test |
| `backtest.py` | backtest-smoke | Strategy validation |

**Benefits:**
- Consistency between local dev and CI
- Single source of truth for operations
- Easy to reproduce CI failures locally
- Fewer moving parts

---

## Local Reproduction

To reproduce CI failures locally:

```bash
# Activate conda environment
conda activate crypto-bot

# Run same commands as CI
python scripts/preflight.py --mode dev --strict
python scripts/mcp_smoke.py --verbose
python scripts/redis_cloud_smoke.py --duration 0  # if REDIS_URL set
python scripts/backtest.py smoke --quick
pytest -q --cov=. --cov-report=xml
ruff check .
mypy . --ignore-missing-imports
```

---

## Required Secrets

Configure in GitHub repo settings → Secrets → Actions:

| Secret | Required | Purpose | Example |
|--------|----------|---------|---------|
| `REDIS_URL` | Optional | Redis Cloud TLS connection | `redis://default:password@redis-19818...` |

**Note:** If `REDIS_URL` is not set, the `redis-smoke` job will be skipped.

---

## Artifacts

### Uploaded by CI

1. **Coverage Report** (codecov)
   - Coverage: XML format
   - Job: test
   - Destination: Codecov.io

2. **Bandit Security Report** (artifact)
   - Format: JSON
   - Job: security
   - Retention: 90 days

3. **Build Artifacts** (artifact)
   - Package: wheel + sdist
   - Job: build
   - Retention: 90 days

---

## Failure Handling

### Critical Failures (Pipeline Stops)

Jobs that **must pass** for pipeline to continue:
- ✅ Preflight Checks
- ✅ MCP Smoke Test
- ✅ Tests (pytest)
- ✅ Build Package

### Non-Blocking Failures

Jobs that can fail without stopping pipeline:
- ⚠️ Linting (ruff)
- ⚠️ Type Checking (mypy)
- ⚠️ Security Checks (safety, bandit)

### Conditional Jobs

Jobs that may be skipped:
- 🔀 Redis Smoke (requires `REDIS_URL` secret)

---

## Optimization Features

### Dependency Caching

All jobs cache pip dependencies:

```yaml
- name: Cache pip dependencies
  uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements*.txt', 'setup.py') }}
```

**Benefit:** ~30-60 seconds faster on cache hit

### Parallel Execution

Jobs run in parallel when possible:
- `preflight` + `mcp-smoke` (parallel)
- `test` + `redis-smoke` (parallel after preflight)

**Benefit:** ~50% faster than sequential

### Timeouts

All network jobs have timeouts:
- MCP Smoke: 2 minutes
- Redis Smoke: 3 minutes
- Backtest Smoke: 5 minutes

**Benefit:** Prevents hung jobs from blocking pipeline

---

## Python Version

**Required:** Python 3.10.18 (exactly)

All jobs use:
```yaml
- name: Set up Python 3.10.18
  uses: actions/setup-python@v5
  with:
    python-version: "3.10.18"
```

**Consistency:** Matches production environment and conda env `crypto-bot`

---

## Branch Triggers

Pipeline runs on:
- Push to: `main`, `master`, `develop`
- Pull requests to: `main`, `master`, `develop`

```yaml
on:
  push:
    branches: [ main, master, develop ]
  pull_request:
    branches: [ main, master, develop ]
```

---

## Monitoring

### CI Badge

Add to README.md:
```markdown
[![CI](https://github.com/<org>/<repo>/workflows/CI/badge.svg)](https://github.com/<org>/<repo>/actions)
```

### Pipeline Status

Check pipeline status:
- GitHub Actions tab → CI workflow
- README badge (green = passing, red = failing)

---

## Troubleshooting

### "Preflight checks failed"

**Cause:** Environment validation failed

**Solution:**
```bash
# Run locally to debug
python scripts/preflight.py --mode dev --strict
```

### "MCP smoke test failed"

**Cause:** Schema validation or JSON marshaling issue

**Solution:**
```bash
# Run locally with verbose output
python scripts/mcp_smoke.py --verbose
```

### "Redis smoke test skipped"

**Cause:** `REDIS_URL` secret not set

**Solution:**
1. Go to GitHub repo settings → Secrets → Actions
2. Add secret: `REDIS_URL`
3. Value: `redis://default:<password>@redis-19818...`

### "Tests failed with import errors"

**Cause:** Missing dependencies

**Solution:**
```bash
# Ensure all dependencies installed
pip install -e .
```

---

## Comparison: Old vs New CI

### Old CI (Before Refactoring)

```yaml
jobs:
  test:
    - pytest
    - ruff
    - mypy
  build:
    - python -m build
  security:
    - safety check
    - bandit
```

**Issues:**
- No preflight checks
- No schema validation
- No Redis testing
- No backtest validation
- 3 jobs, ~2-3 minutes

### New CI (After Refactoring)

```yaml
jobs:
  preflight:        # NEW: Environment validation
  mcp-smoke:        # NEW: Schema testing (hermetic)
  test:
  redis-smoke:      # NEW: Redis Cloud TLS test (conditional)
  backtest-smoke:   # NEW: Strategy validation
  security:
  build:
```

**Improvements:**
- ✅ Uses canonical scripts only
- ✅ Preflight checks before tests
- ✅ Hermetic schema testing
- ✅ Redis Cloud TLS validation
- ✅ Backtest smoke testing
- ✅ 7 jobs, ~2-3 minutes (same duration, more coverage)
- ✅ Parallel execution where possible
- ✅ Conditional jobs (Redis)
- ✅ Better artifact management

---

**Last Updated:** 2025-01-13
**Conda Environment:** crypto-bot
**Python Version:** 3.10.18
**Redis Cloud:** redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818 (TLS)
