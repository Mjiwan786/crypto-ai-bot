# Comprehensive Test Suite Documentation

**Version:** 1.0.0
**Last Updated:** 2025-11-17
**Author:** QA Team

---

## Table of Contents

1. [Overview](#overview)
2. [Test Categories](#test-categories)
3. [Setup Instructions](#setup-instructions)
4. [Running Tests Locally](#running-tests-locally)
5. [Running Tests in CI](#running-tests-in-ci)
6. [Test Configuration](#test-configuration)
7. [Writing New Tests](#writing-new-tests)
8. [Troubleshooting](#troubleshooting)

---

## Overview

This comprehensive test suite ensures reliability and prevents regressions across the entire crypto AI trading platform. The suite covers:

- **Unit Tests**: Model inference, risk guardrails, PnL calculations
- **Integration Tests**: Redis connections, API endpoints, SSE streaming
- **Performance Tests**: Latency <500ms, throughput, load testing
- **End-to-End Tests**: Complete signal flow from generation to display
- **Frontend Tests**: UI functionality, SSE updates, graceful degradation

### Test Coverage

- **crypto-ai-bot**: ML models, signal generation, Redis publishing
- **signals-api**: REST endpoints, SSE streaming, Redis consumption
- **signals-site**: Frontend UI, real-time updates, error handling

---

## Test Categories

### 1. Unit Tests

**File**: `tests/test_signal_generation.py`, `tests/ml/test_ml_system.py`

**Coverage**:
- Model inference latency (<100ms)
- Output validity (probabilities sum to 1.0)
- Regime detection
- Risk guardrails (confidence thresholds, position sizing)
- PnL calculations (fees, cumulative PnL, Sharpe ratio)
- Signal generation and validation

**Run**:
```bash
pytest tests/test_signal_generation.py -v
pytest tests/ml/test_ml_system.py -v
```

### 2. Integration Tests

**File**: `tests/test_integration.py`

**Coverage**:
- Redis connection and operations
- Stream publishing and consumption
- API endpoints (`/v1/signals`, `/v1/pnl`, `/health`)
- SSE connection and streaming
- Redis reconnection after failure
- Concurrent operations

**Run**:
```bash
pytest tests/test_integration.py -v
```

### 3. Performance Tests

**File**: `tests/test_performance.py`

**Coverage**:
- API latency (<500ms target)
- Redis operation latency
- End-to-end signal flow latency
- Concurrent load testing (50+ requests)
- Throughput (Redis, API)
- Uptime monitoring (99.8% target)
- Scalability under increasing load

**Run**:
```bash
pytest tests/test_performance.py -v -s
```

### 4. End-to-End Tests

**File**: `tests/test_end_to_end.py`

**Coverage**:
- Complete flow: WebSocket → Feature Engineering → ML → Redis → API
- Signal flow latency (<1s total)
- API signal retrieval
- SSE stream latency
- Data integrity through system
- Graceful degradation
- Error recovery

**Run**:
```bash
pytest tests/test_end_to_end.py -v -s
```

### 5. Frontend Tests (Playwright)

**File**: `signals-site/tests/e2e/signals.spec.ts`

**Coverage**:
- Homepage loading
- Signals dashboard display
- SSE updates within 1 second
- Real-time signal updates
- PnL metrics display
- Graceful degradation when API down
- Performance (load time <3s)
- Accessibility (keyboard navigation, alt text)
- Error handling and retry

**Run**:
```bash
cd signals-site
npx playwright test
```

---

## Setup Instructions

### Prerequisites

1. **Python 3.10+** (for crypto-ai-bot tests)
2. **Node.js 18+** (for frontend tests)
3. **Redis Cloud** connection (credentials in `.env`)
4. **Conda environment** (optional but recommended)

### Crypto-AI-Bot Setup

```bash
# Create conda environment
conda create -n crypto-bot python=3.10
conda activate crypto-bot

# Install dependencies
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install pandas numpy scikit-learn scipy redis boto3 tqdm requests
pip install pytest pytest-cov pytest-timeout pytest-xdist sseclient-py psutil

# Set environment variables
export REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818"
export API_URL="https://signals-api-gateway.fly.dev"
```

### Signals-Site Setup

```bash
cd signals-site

# Install dependencies
npm install

# Install Playwright browsers
npx playwright install --with-deps

# Set environment variables
export SITE_URL="http://localhost:3000"
export API_URL="https://signals-api-gateway.fly.dev"
```

---

## Running Tests Locally

### All Unit Tests

```bash
cd crypto_ai_bot
pytest tests/test_signal_generation.py tests/ml/test_ml_system.py -v --cov=ml --cov-report=html
```

### All Integration Tests

```bash
pytest tests/test_integration.py -v -s
```

### Performance Tests

```bash
pytest tests/test_performance.py -v -s --timeout=600
```

### End-to-End Tests

```bash
pytest tests/test_end_to_end.py -v -s
```

### Frontend Tests

```bash
cd signals-site

# All tests
npx playwright test

# Specific browser
npx playwright test --project=chromium

# Headed mode (see browser)
npx playwright test --headed

# Debug mode
npx playwright test --debug

# Specific test file
npx playwright test tests/e2e/signals.spec.ts
```

### Run All Tests (Full Suite)

```bash
# Backend tests
pytest tests/ -v --maxfail=5 --timeout=300

# Frontend tests
cd signals-site && npx playwright test
```

---

## Running Tests in CI

Tests run automatically on:
- **Push** to `main`, `develop`, or `feature/**` branches
- **Pull Requests** to `main` or `develop`
- **Daily Schedule** (00:00 UTC for backend, 02:00 UTC for frontend)

### GitHub Actions Workflows

#### crypto-ai-bot: `.github/workflows/test_suite.yml`

Jobs:
1. `unit-tests`: Unit tests with coverage
2. `integration-tests`: Integration tests with Redis/API
3. `performance-tests`: Performance and load tests
4. `end-to-end-tests`: E2E signal flow tests
5. `security-scan`: Bandit security scanning
6. `test-summary`: Aggregate results

#### signals-site: `.github/workflows/e2e-tests.yml`

Jobs:
1. `e2e-tests`: Playwright E2E tests
2. `lighthouse-audit`: Performance audit
3. `accessibility-tests`: Accessibility validation
4. `visual-regression`: Visual diff testing
5. `test-summary`: Aggregate results

### View Results

- Go to GitHub Actions tab
- Click on workflow run
- View job logs and artifacts
- Download test reports

---

## Test Configuration

### pytest Configuration

**File**: `pytest.ini` or `pyproject.toml`

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks tests as integration tests
    e2e: marks tests as end-to-end tests
timeout = 300
```

### Playwright Configuration

**File**: `signals-site/playwright.config.ts`

Key settings:
- Base URL: `http://localhost:3000`
- Browsers: Chrome, Firefox, Safari, Mobile
- Retries: 2 on CI, 0 locally
- Screenshots: On failure
- Videos: On failure
- Trace: On first retry

### Environment Variables

Required for testing:

```bash
# Redis
REDIS_URL="rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.cloud.redislabs.com:19818"

# API
API_URL="https://signals-api-gateway.fly.dev"

# Frontend
SITE_URL="http://localhost:3000"
```

---

## Writing New Tests

### Adding Unit Tests

1. Create test file: `tests/test_feature.py`
2. Use pytest decorators: `@pytest.fixture`, `@pytest.mark.parametrize`
3. Follow naming convention: `test_<feature>_<scenario>`
4. Add assertions with descriptive messages

Example:
```python
def test_signal_confidence_threshold():
    """Test that low-confidence signals are filtered."""
    signal = {'signal': 'LONG', 'confidence': 0.45}
    MIN_CONFIDENCE = 0.6

    should_trade = signal['confidence'] >= MIN_CONFIDENCE
    assert not should_trade, "Should not trade on low confidence"
```

### Adding Integration Tests

1. Use fixtures for setup/teardown
2. Test real connections (Redis, API)
3. Handle failures gracefully (use `pytest.skip()` if service unavailable)
4. Clean up resources after tests

Example:
```python
@pytest.fixture
def redis_client():
    client = redis.from_url(REDIS_URL)
    yield client
    client.close()

def test_redis_publish(redis_client):
    message_id = redis_client.xadd('test_stream', {'data': 'test'})
    assert message_id is not None
    redis_client.delete('test_stream')
```

### Adding Frontend Tests

1. Create test in `tests/e2e/*.spec.ts`
2. Use Page Object Model for reusability
3. Test real user flows
4. Handle async operations properly

Example:
```typescript
test('should display signals within 1 second', async ({ page }) => {
  await page.goto('/signals');

  const signal = page.locator('[data-testid="signal"]').first();
  await expect(signal).toBeVisible({ timeout: 1000 });
});
```

---

## Troubleshooting

### Common Issues

#### 1. Redis Connection Errors

**Symptom**: `redis.ConnectionError: Error connecting to Redis`

**Solution**:
- Check `REDIS_URL` environment variable
- Verify Redis Cloud connection: `redis-cli -u <REDIS_URL> ping`
- Ensure SSL/TLS is enabled: `--tls` flag
- Check firewall/network settings

#### 2. API Timeout

**Symptom**: `requests.Timeout: HTTPSConnectionPool(...): Read timed out`

**Solution**:
- Verify API is running: `curl https://signals-api-gateway.fly.dev/health`
- Increase timeout: `requests.get(..., timeout=30)`
- Check API logs on Fly.io
- Use `pytest.skip()` if API is down

#### 3. Playwright Browser Not Found

**Symptom**: `Error: browserType.launch: Executable doesn't exist`

**Solution**:
```bash
npx playwright install --with-deps
```

#### 4. Test Fails on CI but Passes Locally

**Causes**:
- Timing issues (use proper waits)
- Environment differences (check env vars)
- Network latency (increase timeouts on CI)
- Concurrency issues

**Solution**:
- Add retries: `retries: 2` in playwright.config.ts
- Use `waitForLoadState('networkidle')`
- Increase timeouts on CI: `timeout: 30 * 1000`

#### 5. Memory Issues During Tests

**Symptom**: `MemoryError` or tests getting killed

**Solution**:
- Run tests in smaller batches: `pytest -k "not slow"`
- Increase swap space on CI
- Clean up resources in fixtures
- Use `pytest-xdist` for parallel execution: `pytest -n auto`

### Getting Help

- Check test logs: `pytest -v -s --tb=long`
- Run single test: `pytest tests/test_file.py::test_function -v`
- Debug mode: `pytest --pdb` (drops into debugger on failure)
- Playwright debug: `npx playwright test --debug`

---

## Test Metrics & Targets

### Performance Targets

| Metric | Target | Test |
|--------|--------|------|
| Model Inference | <100ms | `test_model_inference_latency` |
| API Response | <500ms | `test_api_latency_single_request` |
| E2E Signal Flow | <1000ms | `test_complete_signal_flow` |
| Frontend Load | <3s | `should load within 3 seconds` |
| SSE Update | <1s | `should receive SSE updates within 1 second` |
| Uptime | >99.8% | `test_api_availability_over_time` |

### Coverage Targets

- Unit Tests: >80% code coverage
- Integration Tests: All critical paths covered
- E2E Tests: All user flows covered
- Frontend: All pages and components tested

---

## Continuous Improvement

### Adding New Tests

When adding features:
1. Write unit tests first (TDD)
2. Add integration tests for external dependencies
3. Add E2E tests for user-facing features
4. Update this documentation

### Monitoring Test Health

- Review test failures weekly
- Update flaky tests
- Refactor slow tests
- Remove obsolete tests

---

## Quick Reference

```bash
# Run all backend tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=ml --cov-report=html

# Run specific test
pytest tests/test_integration.py::TestRedisIntegration::test_redis_connection -v

# Run frontend tests
cd signals-site && npx playwright test

# Run frontend tests (headed)
npx playwright test --headed --project=chromium

# Run specific frontend test
npx playwright test tests/e2e/signals.spec.ts -g "should load homepage"

# Generate test report
pytest tests/ --html=report.html --self-contained-html

# Run tests with markers
pytest -m "not slow" -v
```

---

**For Questions**: Contact QA Team
**For Issues**: Create GitHub issue with `[TEST]` prefix
**For CI Failures**: Check GitHub Actions logs and artifacts
