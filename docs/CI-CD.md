# CI/CD Pipeline Documentation - crypto-ai-bot

**Repository**: `crypto-ai-bot`
**Last Updated**: 2025-11-16
**Maintainer**: DevOps Team

---

## Overview

This document describes the complete CI/CD pipeline for the crypto-ai-bot repository, from code commit to production deployment. All pipeline configurations align with **[PRD-001: Crypto AI Bot](PRD-001-CRYPTO-AI-BOT.md)**.

### Pipeline Philosophy

- **Quality Gates**: Every commit must pass linting, type checking, tests, and PRD checklist validation
- **Fail Fast**: CI fails immediately on any test failure or unchecked PRD items
- **Automated Deployment**: Successful main branch builds trigger automatic deployment to Fly.io
- **Traceability**: Every deployment is traceable to a specific commit and test run

---

## CI/CD Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        COMMIT TO GITHUB                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Trigger CI/CD  │
                    │  GitHub Actions │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
      ┌─────▼─────┐    ┌────▼────┐    ┌─────▼─────┐
      │   Lint    │    │  Test   │    │  Build    │
      │   & Type  │    │         │    │           │
      │   Check   │    │         │    │           │
      └─────┬─────┘    └────┬────┘    └─────┬─────┘
            │                │                │
            │                │                │
            └────────┬───────┴────────┬───────┘
                     │                │
              ┌──────▼──────┐  ┌──────▼──────┐
              │ PRD Checklist│  │  Security   │
              │  Validation  │  │  Scan       │
              └──────┬──────┘  └──────┬──────┘
                     │                │
                     └────────┬───────┘
                              │
                     ┌────────▼────────┐
                     │  All Checks Pass │
                     └────────┬────────┘
                              │
                     ┌────────▼────────┐
                     │ Deploy to Fly.io│
                     │   (main only)   │
                     └────────┬────────┘
                              │
                     ┌────────▼────────┐
                     │  PRODUCTION     │
                     └─────────────────┘
```

---

## Workflows

### 1. Main CI Workflow (`.github/workflows/ci.yml`)

**Trigger**: Push or Pull Request to `main` or `develop` branches

**Jobs**:

#### 1.1 Test Job

- **Python Version**: 3.10.18 (as per PRD-001)
- **Steps**:
  1. Checkout code
  2. Set up Python 3.10.18
  3. Cache pip dependencies
  4. Install dependencies (`pip install -e .`)
  5. Lint with `ruff`
  6. Type check with `mypy`
  7. Run tests with `pytest`
  8. **Validate PRD-001 Checklist** (✨ enforces completion)

**Exit Criteria**: All steps must pass with exit code 0

#### 1.2 Build Job

- **Depends On**: Test job success
- **Steps**:
  1. Checkout code
  2. Set up Python 3.10.18
  3. Install build dependencies
  4. Build package (`python -m build`)
  5. Verify build artifacts with `twine check`

#### 1.3 Security Job

- **Depends On**: Test job success
- **Steps**:
  1. Checkout code
  2. Set up Python 3.10.18
  3. Run `safety` check (dependency vulnerabilities)
  4. Run `bandit` security linter
  5. Upload security report as artifact

### 2. Backtest on Strategy Change (`.github/workflows/backtest-on-strategy-change.yml`)

**Trigger**: Changes to `agents/strategies/*.py` files

**Purpose**: Automatically run backtests when trading strategies are modified

**Steps**:
1. Detect strategy file changes
2. Run backtests for affected strategies
3. Generate performance reports
4. Upload backtest results as artifacts

### 3. Fly.io Deployment (`.github/workflows/fly-deploy.yml`)

**Trigger**: Manual workflow dispatch or successful CI on `main` branch

**Steps**:
1. Checkout code
2. Set up Fly.io CLI
3. Deploy to Fly.io: `fly deploy --remote-only`

**Environment Variables** (set in GitHub Secrets):
- `FLY_API_TOKEN`: Fly.io authentication token

---

## PRD Checklist Validation

### Purpose

Ensures all PRD-001 requirements are implemented before merging code. This prevents incomplete features from reaching production.

### Implementation

**Script**: `scripts/check_prd_checklist.py`

**What it does**:
1. Reads `docs/PRD-001-CHECKLIST.md`
2. Counts checked `[x]` vs unchecked `[ ]` items
3. Exits with code 1 if any items are unchecked
4. Exits with code 0 if all items are checked

**Usage**:
```bash
# Run locally
python scripts/check_prd_checklist.py

# Expected output (if items pending):
[*] PRD-001 Checklist Validation
============================================================
[>] Checklist: /path/to/docs/PRD-001-CHECKLIST.md

Total items:     150
Checked [x]:     120
Unchecked [ ]:   30

Completion: 80.0%

[-] FAILURE: 30 unchecked item(s) found!
    Cannot merge until all items are checked off.

Unchecked items (first 10):
------------------------------------------------------------
  1. Line 45: - [ ] Implement Redis reconnection logic
  2. Line 67: - [ ] Add circuit breaker to Kraken API client
  ...
```

### CI Integration

The PRD checklist validation runs as the **last step** of the test job:

```yaml
- name: Validate PRD Checklist
  run: |
    echo "Validating PRD-001 checklist completion..."
    python scripts/check_prd_checklist.py
```

**Behavior**:
- ✅ **Success**: All items checked → CI passes → merge allowed
- ❌ **Failure**: Unchecked items found → CI fails → merge blocked

---

## Environment Configuration

### GitHub Secrets

Configure these secrets in **Settings → Secrets and variables → Actions**:

| Secret | Purpose | Example |
|--------|---------|---------|
| `FLY_API_TOKEN` | Fly.io deployment authentication | `fly_api_token_...` |

### Environment Variables (Local Development)

For local testing, configure these in `.env.local`:

```bash
# Redis Cloud Connection
REDIS_URL=rediss://default:Salam78614%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818
REDIS_SSL=true
REDIS_SSL_CA_CERT=config/certs/redis_ca.pem

# Trading Mode
TRADING_MODE=paper  # or 'live'

# Conda Environment
# Use: conda activate crypto-bot
```

---

## Deployment Process

### Automatic Deployment (Main Branch)

**Trigger**: Push to `main` branch after CI passes

**Process**:
1. Code merged to `main`
2. CI workflow runs (lint, test, build, security)
3. PRD checklist validation passes
4. Fly.io deployment workflow triggers
5. Application deployed to `https://crypto-ai-bot.fly.dev`
6. Health checks verify deployment success

### Manual Deployment

**Via GitHub Actions UI**:
1. Go to **Actions** tab
2. Select "Fly.io Deploy" workflow
3. Click "Run workflow"
4. Select branch (typically `main`)
5. Click "Run workflow" button

**Via Fly.io CLI** (local):
```bash
# Ensure you're logged in
fly auth login

# Deploy from local machine
fly deploy

# View logs
fly logs -a crypto-ai-bot

# Check status
fly status -a crypto-ai-bot
```

### Rollback Procedure

If a deployment causes issues:

```bash
# List recent releases
fly releases -a crypto-ai-bot

# Rollback to previous version (e.g., v42)
fly releases revert v42 -a crypto-ai-bot

# Verify rollback
fly status -a crypto-ai-bot
```

---

## Testing Locally Before Commit

### Run Full CI Suite Locally

```bash
# Activate conda environment
conda activate crypto-bot

# Lint code
ruff check .

# Type check
mypy .

# Run tests
pytest -q

# Validate PRD checklist
python scripts/check_prd_checklist.py

# Build package
python -m build

# Security scan
safety check --file requirements.txt
bandit -r . -f json -o bandit-report.json
```

### Quick Pre-Commit Check

```bash
# Fast check (skips build and security)
ruff check . && mypy . && pytest -q && python scripts/check_prd_checklist.py
```

---

## Monitoring & Observability

### CI/CD Monitoring

- **GitHub Actions Dashboard**: View workflow runs in the Actions tab
- **Build Status Badge**: Add to README for visibility
  ```markdown
  [![CI](https://github.com/user/crypto-ai-bot/workflows/CI/badge.svg)](https://github.com/user/crypto-ai-bot/actions)
  ```

### Production Monitoring

- **Fly.io Dashboard**: https://fly.io/apps/crypto-ai-bot
- **Health Checks**: `curl https://crypto-ai-bot.fly.dev/health`
- **Logs**: `fly logs -a crypto-ai-bot`
- **Metrics**: Prometheus metrics at `/metrics` endpoint

---

## Common Issues & Troubleshooting

### Issue: PRD Checklist Validation Fails

**Symptom**: CI fails with "FAILURE: X unchecked item(s) found!"

**Solution**:
1. Review `docs/PRD-001-CHECKLIST.md`
2. Mark completed items with `[x]`
3. If items are truly incomplete, finish implementing them
4. Commit updated checklist and push

**Bypass** (not recommended for production):
- PRD checklist validation cannot be bypassed in CI
- This is intentional to ensure PRD compliance

### Issue: Fly.io Deployment Fails

**Symptom**: Deployment workflow fails during `fly deploy`

**Possible Causes**:
1. Invalid `FLY_API_TOKEN` secret
2. Dockerfile build failure
3. Fly.io service outage

**Solution**:
```bash
# Check Fly.io status
fly status -a crypto-ai-bot

# View deployment logs
fly logs -a crypto-ai-bot

# Verify Fly.io token is valid
fly auth whoami

# Re-deploy manually
fly deploy --verbose
```

### Issue: Tests Pass Locally But Fail in CI

**Symptom**: `pytest` succeeds locally but fails in GitHub Actions

**Possible Causes**:
1. Different Python version (CI uses 3.10.18)
2. Missing dependencies in `requirements.txt`
3. Environment-specific configuration

**Solution**:
```bash
# Use exact Python version as CI
conda create -n test-ci python=3.10.18
conda activate test-ci

# Install from requirements.txt (like CI does)
pip install -r requirements.txt

# Run tests
pytest -v
```

---

## Pipeline Metrics & SLOs

### Success Criteria

- ✅ **CI Pass Rate**: >95% (excluding expected failures from WIP branches)
- ✅ **Deployment Success Rate**: >99%
- ✅ **CI Runtime**: <10 minutes for full pipeline
- ✅ **Deployment Time**: <5 minutes from push to production

### Current Performance

View real-time metrics:
- [GitHub Actions Insights](https://github.com/user/crypto-ai-bot/actions)
- Workflow duration trends
- Success/failure rates

---

## Best Practices

### For Developers

1. **Run tests locally before pushing**:
   ```bash
   pytest -q && python scripts/check_prd_checklist.py
   ```

2. **Keep PRD checklist up-to-date**:
   - Mark items as complete `[x]` immediately after implementation
   - Don't merge PRs with unchecked items

3. **Write meaningful commit messages**:
   - Good: `feat: add Redis reconnection logic with exponential backoff`
   - Bad: `fix stuff`

4. **Review CI logs on failures**:
   - Click "Details" next to failed checks
   - Read error messages carefully
   - Fix issues before re-pushing

### For Maintainers

1. **Monitor deployment health**:
   ```bash
   fly logs -a crypto-ai-bot
   ```

2. **Keep dependencies updated**:
   - Review Dependabot PRs weekly
   - Test security updates in staging first

3. **Review security scan reports**:
   - Download `bandit-report.json` artifacts
   - Address high-severity findings promptly

---

## Related Documentation

- **[PRD-001: Crypto AI Bot](PRD-001-CRYPTO-AI-BOT.md)** - Authoritative requirements
- **[PRD-001 Checklist](PRD-001-CHECKLIST.md)** - Implementation tracking
- **[README.md](../README.md)** - Repository overview
- **[OPERATIONS.md](OPERATIONS.md)** - Operational procedures
- **[PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md)** - Detailed deployment guide

---

## Support & Contact

**CI/CD Issues**: Open an issue with the `ci/cd` label
**Deployment Issues**: Tag `@devops-team` in issues or Slack
**PRD Questions**: Tag `@product-team`

---

**Last Updated**: 2025-11-16
**Next Review**: Monthly or when pipeline changes are made
